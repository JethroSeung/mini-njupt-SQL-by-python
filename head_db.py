#---------------------------------
# head_db.py
# author: Jingyu Han    hjymail@163.com
#--------------------------------------
#
# 表模式(Schema)的内存缓存结构
#
# 整体逻辑:
#   Header 类是 all.sch 文件内容在内存中的缓存对象。
#   程序启动时，Schema.__init__ 读取 all.sch 并构建 Header 对象；
#   后续对 schema 的增删操作只修改 Header 内存，不立即写盘；
#   程序退出时，若 Header.dirty 为 True，则由 Schema.__del__ 调用
#   WriteBuff() 将内存数据统一写回 all.sch（lazy write 策略）。
#
# 函数分工:
#   __init__      - 构造函数，初始化表名列表、字段字典、脏标志等
#   __del__       - 析构函数
#   mark_dirty    - 标记缓存已被修改，需要写回磁盘
#   is_dirty      - 查询缓存是否被修改过
#   showTables    - 显示所有表的名称和字段信息（调试用）
#
# 核心数据结构:
#   tableNames  : list of (table_name(str), num_of_fields(int), offset_in_body(int))
#   tableFields : dict {table_name(str): [(field_name(str), field_type(int), field_length(int)), ...]}
#   dirty       : bool，脏标志位，True 表示内存数据已被修改需写盘
#------------------------------------
import struct



class Header(object):
    #------------------------
    # 构造函数：初始化 Header 内存缓存对象
    # input
    #   nameList    : list of triples (table_name(str), num_of_fields(int), offset_in_body(int))
    #   fieldDict   : dict {table_name(str): [(field_name(str), field_type(int), field_length(int)), ...]}
    #   inistored   : bool, whether schema data exists
    #   inLen       : number of tables
    #   off         : where the free space begins in body of the schema file
    #---------------------------------------------------------------
    def __init__(self,nameList,fieldDict,inistored, inLen, off):

        self.isStored=inistored # whether it is stored
        self.lenOfTableNum=inLen # number of tables
        self.offsetOfBody=off    # body 中空闲区域的起始偏移
        self.tableNames=nameList # 表名三元组列表
        self.tableFields=fieldDict # 字段信息字典
        self.dirty=False  # 脏标志位：True 表示内存已被修改，需要写回磁盘

    #-----------------------------
    # 析构函数
    #-------------------------------
    def __del__(self):
        pass

    #-----------------------------
    # 标记缓存为已修改（脏）
    # 在 appendTable / delete_table_schema / deleteAll 中调用
    #-------------------------------
    def mark_dirty(self):
        self.dirty=True

    #-----------------------------
    # 查询缓存是否被修改过
    # output: bool
    #-------------------------------
    def is_dirty(self):
        return self.dirty

    #-----------------------------
    # 显示所有表的名称和字段信息（调试用）
    #----------------------------------------------------------
    def showTables(self):
        if self.lenOfTableNum>0:
            for i in range(len(self.tableNames)):
                print(self.tableNames[i])
                table_name = self.tableNames[i][0]
                if table_name in self.tableFields:
                    print(self.tableFields[table_name])
