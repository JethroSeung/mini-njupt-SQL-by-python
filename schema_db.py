#-----------------------------------------------
# schema_db.py
# author: Jingyu Han   hjymail@163.com
# modified by: Ning wang, Yidan Xu
#-----------------------------------------------
#
# 表模式(Schema)的磁盘存储与内存管理
#
# 整体逻辑:
#   all.sch 文件存储所有表的模式信息，分为三段：
#     metaHead     (12字节)  : 是否有数据、表数量、body空闲偏移
#     tableNameHead (固定大小): 每个表的(表名, 字段数, body偏移)
#     body          (固定大小): 每个表的字段信息(字段名, 类型, 长度)
#
#   Schema 类负责 all.sch 的读写，并维护 Header 内存缓存。
#   采用 lazy write 策略：增删操作只改内存，标脏后延迟到程序退出时写盘。
#
# 函数分工:
#   __init__            - 读取 all.sch，构建 Header 内存缓存
#   __del__             - 程序退出时，若缓存脏则调 WriteBuff 写盘
#   appendTable         - 新增一张表的模式（只改内存，标脏）
#   delete_table_schema - 删除一张表的模式（只改内存，标脏）
#   deleteAll           - 清空所有表模式（只改内存，标脏）
#   find_table          - 查询某表是否存在
#   get_table_name_list - 返回所有表名列表
#   viewTableStructure  - 显示指定表的字段结构
#   viewTableNames      - 显示所有表名
#   WriteBuff           - 将 Header 内存数据全量写回 all.sch
#
# 编码策略:
#   内存中统一使用 str，仅在 struct.pack 前编码为 bytes，
#   在 struct.unpack 后立即解码为 str。
#-------------------------------------------

import ctypes
import struct
import head_db # it is main memory structure for the table schema

try:
    from rich.console import Console
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False





#the following is metaHead structure,which is 12 bytes
"""
isStored    # whether there is data in the all.sch
tableNum    # how many tables
offset      # where the free area begins for body.
"""
META_HEAD_SIZE=12                                           # metaHead 固定 12 字节


#the following is the structure of tableNameHead
"""
tablename|numofFeilds|beginOffsetInBody|....|tablename|numofFeilds|beginOffsetInBody|
10 bytes |4 bytes    |4 bytes
"""
MAX_TABLE_NAME_LEN=10                                       # 表名最大长度
MAX_TABLE_NUM=100                                           # 最大表数量
TABLE_NAME_ENTRY_LEN=MAX_TABLE_NAME_LEN+4+4                 # 每个表名条目的长度: 10+4+4=18
TABLE_NAME_HEAD_SIZE=MAX_TABLE_NUM*TABLE_NAME_ENTRY_LEN     # tableNameHead 总大小



# the following is for body, which stores the field information of each table and the field information is as follows
"""
field_name   # it is a string
field_type   # it is an integer, 0->str,1->varstr,2->int,3->bool
field_length # it is an integer
"""
MAX_FIELD_NAME_LEN=10                                       # 字段名最大长度
MAX_FIELD_LEN=10+4+4                                         # 每个字段条目的长度: 10+4+4=18
MAX_NUM_OF_FIELD_PER_TABLE=5                                # 每张表最大字段数
FIELD_ENTRY_SIZE_PER_TABLE=MAX_FIELD_LEN*MAX_NUM_OF_FIELD_PER_TABLE
MAX_FIELD_SECTION_SIZE=FIELD_ENTRY_SIZE_PER_TABLE*MAX_TABLE_NUM # body 总大小



BODY_BEGIN_INDEX=META_HEAD_SIZE+TABLE_NAME_HEAD_SIZE            # body 区域在文件中的起始偏移


# -----------------------------
# 将表名右对齐填充到 MAX_TABLE_NAME_LEN 长度
# input:  tableName (str)
# output: 填充后的表名 (str)
# -------------------------------
def fillTableName(tableName):
    tableName = tableName.strip()
    if len(tableName) < MAX_TABLE_NAME_LEN:
        tableName = ' ' * (MAX_TABLE_NAME_LEN - len(tableName)) + tableName
    return tableName


class Schema(object):
    '''
    Schema class
    '''

    fileName = 'all.sch'  # the schema file name
    count = 0  # there should be only one object in the program

    @staticmethod
    def how_many():  # give the count of instances
        return Schema.count


    def viewTableNames(self):  # 显示所有表名

        for i in self.headObj.tableNames:
            print ('Table name is     ', i[0])

    #------------------------
    # 显示指定表的字段结构
    # input:  table_name (str)
    # output: 无，直接打印表结构
    #------------------------------
    def viewTableStructure(self, table_name):

        table_name = table_name.strip()

        for name, field_num, _ in self.headObj.tableNames:

            if name.strip() == table_name:

                fields = self.headObj.tableFields.get(table_name, [])

                type_names = {0: 'str', 1: 'varstr', 2: 'int', 3: 'bool'}

                if HAS_RICH:
                    console = Console()
                    table = Table(title=f'Table: {table_name}', show_header=True, header_style="bold magenta", show_lines=True)
                    table.add_column("Field", style="cyan")
                    table.add_column("Type", style="green")
                    table.add_column("Length", style="yellow", justify="right")
                    for f in fields:
                        fname = f[0].strip()
                        ftype = f[1]
                        flen = f[2]
                        tname = type_names.get(ftype, str(ftype))
                        table.add_row(fname, tname, str(flen))
                    console.print(table)
                else:
                    print(f'Table: {table_name}')
                    for f in fields:
                        fname = f[0].strip()
                        ftype = f[1]
                        flen = f[2]
                        tname = type_names.get(ftype, str(ftype))
                        print(f'  {fname:<15} type={tname:<8} len={flen}')
                return

        print("Table not found")

    # ------------------------------------------------
    # 构造函数：读取 all.sch，构建 Header 内存缓存
    # ------------------------------------------------
    def __init__(self):

        # 若 all.sch 不存在则先创建空文件
        import os
        if not os.path.exists(Schema.fileName):
            with open(Schema.fileName, 'wb') as f:
                pass

        self.fileObj = open(Schema.fileName, 'rb+')  # 以二进制格式打开

        # 读取 all.sch 全部内容到 buf
        bufLen = META_HEAD_SIZE + TABLE_NAME_HEAD_SIZE + MAX_FIELD_SECTION_SIZE
        buf = ctypes.create_string_buffer(bufLen)
        buf = self.fileObj.read(bufLen)

        buf.strip()
        if len(buf) == 0:  # all.sch 为空，首次运行
            self.body_begin_index = BODY_BEGIN_INDEX
            buf = struct.pack('!?ii', False, 0, self.body_begin_index)  # 写入初始 metaHead

            self.fileObj.seek(0)
            self.fileObj.write(buf)
            self.fileObj.flush()

            # 创建空的 Header 内存对象
            nameList = []
            fieldsList = {}
            self.headObj = head_db.Header(nameList, fieldsList, False, 0, self.body_begin_index)

        else:  # all.sch 非空，解析已有数据

            # 解析 metaHead：isStored(1字节) + tableNum(4字节) + offset(4字节)
            isStored, tempTableNum, tempOffset = struct.unpack_from('!?ii', buf, 0)

            Schema.body_begin_index = tempOffset
            nameList=[]
            fieldsList={}

            if isStored == False:  # metaHead 存在但无表信息
                self.headObj = head_db.Header(nameList, fieldsList, False, 0, BODY_BEGIN_INDEX)

            else:  # 有表信息，解析 tableNameHead 和 body

                # 解析 tableNameHead：逐个读取表名条目
                for i in range(tempTableNum):
                    # 读取表名（10字节），立即 decode 为 str
                    tempNameBytes, = struct.unpack_from('!10s', buf,
                                                   META_HEAD_SIZE + i * TABLE_NAME_ENTRY_LEN)
                    tempName = tempNameBytes.decode('utf-8').strip()

                    # 读取该表的字段数
                    tempNum, = struct.unpack_from('!i', buf, META_HEAD_SIZE + i * TABLE_NAME_ENTRY_LEN + 10)

                    # 读取该表字段信息在 body 中的偏移
                    tempPos, = struct.unpack_from('!i', buf,
                                                  META_HEAD_SIZE + i * TABLE_NAME_ENTRY_LEN + 10 + struct.calcsize('i'))

                    tempNameMix = (tempName, tempNum, tempPos)
                    nameList.append(tempNameMix)

                    # 解析 body：逐个读取字段信息
                    if tempNum > 0:
                        fields = []
                        for j in range(tempNum):
                            tempFieldNameBytes,tempFieldType,tempFieldLength = struct.unpack_from('!10sii',
                                                                                             buf, tempPos + j * MAX_FIELD_LEN)

                            # 读取字段名后立即 decode 为 str
                            tempFieldName = tempFieldNameBytes.decode('utf-8').strip()

                            tempFieldTuple=(tempFieldName,tempFieldType,tempFieldLength)
                            fields.append(tempFieldTuple)

                        fieldsList[tempName]=fields

                # 构造 Header 内存缓存对象
                self.headObj = head_db.Header(nameList, fieldsList, True, tempTableNum, tempOffset)

    # ----------------------------
    # 析构函数：若缓存脏则全量写盘，否则只写 metaHead
    # ----------------------------
    def __del__(self):
        if not hasattr(self, 'headObj') or not hasattr(self, 'fileObj') or self.fileObj is None:
            return

        try:
            if self.headObj.is_dirty():
                # 缓存脏：截断文件后全量写回
                self.fileObj.seek(0)
                self.fileObj.truncate(0)
                self.fileObj.flush()
                self.WriteBuff()
            else:
                # 缓存干净：只写 metaHead 12字节
                buf = ctypes.create_string_buffer(12)
                struct.pack_into('!?ii', buf, 0, self.headObj.isStored, self.headObj.lenOfTableNum, self.headObj.offsetOfBody)
                self.fileObj.seek(0)
                self.fileObj.write(buf)
                self.fileObj.flush()

            self.fileObj.close()
        except Exception:
            pass

    # --------------------------
    # 清空所有表模式（只改内存，标脏，延迟写盘）
    # ----------------------------------------
    def deleteAll(self):
        self.headObj.tableFields={}
        self.headObj.tableNames=[]
        self.headObj.isStored = False
        self.headObj.lenOfTableNum = 0
        self.headObj.offsetOfBody = self.body_begin_index
        self.headObj.mark_dirty()

    # -----------------------------
    # 新增一张表的模式（只改内存，标脏，延迟写盘）
    # input:
    #       tablename: str, 表名
    #       fieldList: list of tuples (field_name(str), field_type(int), field_length(int))
    # -------------------------------
    def appendTable(self, tableName, fieldList):
        tableName = tableName.strip()

        if len(tableName) == 0 or len(tableName) > 10 or len(fieldList)==0:
            print ('tablename is invalid or field list is invalid')
        else:

            fieldNum = len(fieldList)

            # 构造表名三元组：(表名, 字段数, body偏移)
            nameContent = (tableName, fieldNum, self.headObj.offsetOfBody)

            # 修改 Header 内存结构
            self.headObj.isStored = True
            self.headObj.lenOfTableNum += 1
            self.headObj.offsetOfBody += fieldNum * MAX_FIELD_LEN  # 更新 body 空闲偏移
            self.headObj.tableNames.append(nameContent)
            self.headObj.tableFields[tableName]=fieldList
            self.headObj.mark_dirty()

    # -------------------------------
    # 查询某表是否存在
    # input:  table_name (str)
    # output: True or False
    # -------------------------------------------------------
    def find_table(self, table_name):
        table_name = table_name.strip()
        table_names = [x[0].strip() for x in self.headObj.tableNames]
        return table_name in table_names



    # ----------------------------------------------
    # 将 Header 内存数据全量写回 all.sch
    # 写入顺序：metaHead → tableNameHead → body
    # ------------------------------------------------
    def WriteBuff(self):
        bufLen = META_HEAD_SIZE + TABLE_NAME_HEAD_SIZE + MAX_FIELD_SECTION_SIZE
        buf = ctypes.create_string_buffer(bufLen)

        # 写 metaHead
        struct.pack_into('!?ii', buf, 0, self.headObj.isStored, self.headObj.lenOfTableNum, self.headObj.offsetOfBody)

        # 写 tableNameHead 和 body
        for idx in range(len(self.headObj.tableNames)):
            tmp_tableName = self.headObj.tableNames[idx][0].strip()
            # pack 前编码为 bytes
            tmp_tableName_padded = fillTableName(tmp_tableName).encode('utf-8')

            # 写入表名条目：(表名, 字段数, body偏移)
            struct.pack_into('!10sii', buf, META_HEAD_SIZE + idx * TABLE_NAME_ENTRY_LEN, tmp_tableName_padded,
                             self.headObj.tableNames[idx][1],self.headObj.tableNames[idx][2])

            # 写入该表的字段信息到 body
            table_name_key = self.headObj.tableNames[idx][0].strip()
            if table_name_key in self.headObj.tableFields:
                for idj in range(self.headObj.tableNames[idx][1]):
                    (tempFieldName,tempFieldType,tempFieldLength)=self.headObj.tableFields[table_name_key][idj]
                    # pack 前编码为 bytes
                    tempFieldNameBytes = fillTableName(tempFieldName).encode('utf-8')
                    struct.pack_into('!10sii',buf,self.headObj.tableNames[idx][2]+idj*MAX_FIELD_LEN,
                                    tempFieldNameBytes,tempFieldType,tempFieldLength)

        self.fileObj.seek(0)
        self.fileObj.write(buf)
        self.fileObj.flush()

    # ----------------------------------------------
    # 删除一张表的模式（只改内存，标脏，延迟写盘）
    # input:  table_name (str)
    # output: True or False
    # ------------------------------------------------
    def delete_table_schema(self, table_name):
        table_name = table_name.strip()
        tmpIndex=-1
        for i in range(len(self.headObj.tableNames)):
            if self.headObj.tableNames[i][0].strip()==table_name:
                tmpIndex=i
        if tmpIndex>=0:

            # 从内存中删除该表的表名条目和字段信息
            del self.headObj.tableNames[tmpIndex]
            del self.headObj.tableFields[table_name]
            self.headObj.lenOfTableNum-=1

            if len(self.headObj.tableNames)>0: # 删除后仍有表
                name_list = [x[0] for x in self.headObj.tableNames]
                field_num_per_table = [x[1] for x in self.headObj.tableNames]

                # 重新计算剩余表在 body 中的偏移
                table_offset = [BODY_BEGIN_INDEX]
                for idx in range(1, len(self.headObj.tableNames)):
                    table_offset.append(table_offset[idx-1] + field_num_per_table[idx-1]*MAX_FIELD_LEN)

                self.headObj.tableNames = list(zip(name_list, field_num_per_table, table_offset))
                self.headObj.offsetOfBody=self.headObj.tableNames[-1][2]+self.headObj.tableNames[-1][1]*MAX_FIELD_LEN

            else:# 删除后无表
                self.headObj.offsetOfBody = BODY_BEGIN_INDEX
                self.headObj.isStored = False

            self.headObj.mark_dirty()
            return True
        else:
            print ('Cannot find the table!')
            return False

    # ---------------------------
    # 返回所有表名列表
    # output: list of str
    # --------------------------------
    def get_table_name_list(self):
        return [x[0].strip() for x in self.headObj.tableNames]
