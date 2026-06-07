#-----------------------------------------------
# storage_db.py
# author: Jingyu Han   hjymail@163.com
# modified by: Ning Wang, Yidan Xu
#-----------------------------------------------
#
# 表数据(Instance)的磁盘存储与内存管理
#
# 整体逻辑:
#   每张表的数据存储在独立的 .dat 文件中，采用分块(block)结构：
#     block 0 (目录块): 存储表结构(字段名/类型/长度) + 元信息
#     block 1~N (数据块): 存储行记录，每条记录包含：
#       - 记录头: is_deleted(bool) + pointer(int) + length(int) + timestamp(10s)
#       - 记录内容: 各字段值按定义长度拼接
#
#   Storage 类负责 .dat 文件的读写，在内存中维护：
#     record_list    : 所有行记录的列表
#     deleted_flags  : 对应的删除标记列表
#     field_name_list: 字段信息列表 [(field_name, field_type, field_length), ...]
#
#   删除策略: 标记删除 + 延迟压缩
#     delete_by_condition: 标记匹配行为已删除，然后调 persist_records 压缩写回
#   更新策略: 删除旧行 + 插入新行
#     update_by_condition: 标记旧行删除，追加新行，然后调 persist_records 压缩写回
#
# 函数分工:
#   __init__            - 读取 .dat 文件，构建内存结构
#   insert_record       - 插入一行记录，直接写盘
#   delete_by_condition - 按字段条件标记删除行，压缩写回
#   update_by_condition - 按字段条件更新行（删旧插新），压缩写回
#   persist_records     - 压缩：只保留有效行，清空文件后重写
#   show_table_data     - 显示表中所有有效数据
#   getRecord           - 返回所有记录（含已删除）
#   get_valid_records   - 返回有效记录
#   getFieldList        - 返回字段信息列表
#   _to_text            - 将值转为文本
#   _to_bool            - 将值转为布尔
#   _pad_name           - 将名称右对齐填充到指定长度
#
# 编码策略:
#   内存中统一使用 str，仅在 struct.pack 前编码为 bytes，
#   在 struct.unpack 后立即解码为 str。
#-----------------------------------------------

from common_db import BLOCK_SIZE
import struct
import os
import ctypes

try:
    from rich.console import Console
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def _pad_name(name, max_len=10):
    """将名称右对齐填充到 max_len 长度（用前导空格）"""
    name = name.strip()
    if len(name) < max_len:
        name = ' ' * (max_len - len(name)) + name
    return name


class Storage(object):

    # ------------------------------------------------
    # 构造函数：读取 .dat 文件，构建内存结构
    # input:
    #   tablename: str, 表名
    #   skip_init: bool, 为 True 时不交互输入字段信息
    # ------------------------------------------------
    def __init__(self, tablename, skip_init=False):
        if isinstance(tablename, bytes):
            tablename = tablename.decode('utf-8')
        tablename = tablename.strip()

        self.record_list = []       # 所有行记录
        self.record_Position = []   # 每条记录在文件中的位置 (block_id, index_in_block)
        self.deleted_flags = []     # 删除标记列表
        self.field_name_list = []   # 字段信息: [(field_name(str), field_type(int), field_length(int)), ...]
        self.open = False

        file_path = tablename + '.dat'

        # 若 .dat 文件不存在则创建
        if not os.path.exists(file_path):
            f = open(file_path, 'wb+')
            f.close()

        self.f_handle = open(file_path, 'rb+')
        self.open = True

        # 读取 block 0（目录块）
        self.f_handle.seek(0, os.SEEK_END)
        file_size = self.f_handle.tell()
        self.f_handle.seek(0)
        self.dir_buf = self.f_handle.read(BLOCK_SIZE)

        self.block_id = 0
        self.data_block_num = 0
        self.num_of_fields = 0

        # ------------------------------
        # 情况1: 文件为空且需要交互输入字段信息（建新表）
        # ------------------------------
        if file_size == 0 and not skip_init:
            self.num_of_fields = int(input("please input number of fields: "))

            self.dir_buf = ctypes.create_string_buffer(BLOCK_SIZE)
            self.block_id = 0
            self.data_block_num = 0

            # 写 block 0 头部：block_id + data_block_num + num_of_fields
            struct.pack_into('!iii', self.dir_buf, 0, 0, 0, self.num_of_fields)

            offset = struct.calcsize('!iii')

            # 逐个输入字段信息，写入 block 0
            for i in range(self.num_of_fields):
                name = input(f"field {i} name: ").strip()
                ftype = int(input("type(0 str,1 varstr,2 int,3 bool): "))
                flen = int(input("length: "))

                # 内存中存 str，pack 前编码为 bytes
                self.field_name_list.append((name, ftype, flen))
                name_bytes = _pad_name(name).encode('utf-8')
                struct.pack_into('!10sii', self.dir_buf, offset, name_bytes, ftype, flen)
                offset += struct.calcsize('!10sii')

            self.f_handle.seek(0)
            self.f_handle.write(self.dir_buf)
            self.f_handle.flush()

        # ------------------------------
        # 情况2: 文件为空但不需要交互输入
        # ------------------------------
        elif file_size == 0 and skip_init:
            self.block_id = 0
            self.data_block_num = 0
            self.num_of_fields = 0
            self.field_name_list = []

        # ------------------------------
        # 情况3: 文件非空，读取已有数据
        # ------------------------------
        else:
            if len(self.dir_buf) < struct.calcsize('!iii'):
                raise ValueError("corrupted table file header")

            # 读取 block 0 头部
            self.block_id, self.data_block_num, self.num_of_fields = struct.unpack_from('!iii', self.dir_buf, 0)

            # 读取字段信息，unpack 后立即 decode 为 str
            offset = struct.calcsize('!iii')
            for i in range(self.num_of_fields):
                field_bytes, ftype, flen = struct.unpack_from('!10sii', self.dir_buf, offset + i * struct.calcsize('!10sii'))
                fname = field_bytes.decode('utf-8').strip()
                self.field_name_list.append((fname, ftype, flen))

        # ------------------------------
        # 读取数据块中的所有记录
        # ------------------------------
        record_head_len = struct.calcsize('!?ii10s')
        record_content_len = sum(f[2] for f in self.field_name_list)

        if self.data_block_num > 0 and self.num_of_fields > 0:
            for blk in range(1, self.data_block_num + 1):
                self.f_handle.seek(BLOCK_SIZE * blk)
                buf = self.f_handle.read(BLOCK_SIZE)

                if len(buf) < struct.calcsize('!ii'):
                    continue

                # 读取数据块头部：block_id + record_num
                block_id, record_num = struct.unpack_from('!ii', buf, 0)

                for i in range(record_num):
                    # 读取记录偏移量
                    offset_pos = struct.calcsize('!ii') + i * struct.calcsize('!i')
                    if offset_pos + struct.calcsize('!i') > len(buf):
                        continue

                    offset = struct.unpack_from('!i', buf, offset_pos)[0]
                    if offset < 0 or offset + record_head_len > len(buf):
                        continue

                    # -------- 读取记录头 --------
                    is_deleted, pointer, length, ts = struct.unpack_from('!?ii10s', buf, offset)
                    self.deleted_flags.append(is_deleted)
                    self.record_Position.append((blk, i))

                    # -------- 读取记录内容 --------
                    if record_content_len > 0 and offset + record_head_len + record_content_len <= len(buf):
                        content = struct.unpack_from(
                            f'!{record_content_len}s',
                            buf,
                            offset + record_head_len
                        )[0]
                    else:
                        content = b''

                    # 按字段定义拆分记录内容
                    tmp = 0
                    row = []

                    for field in self.field_name_list:
                        val = content[tmp:tmp + field[2]]
                        tmp += field[2]

                        # unpack 后立即 decode 为 str
                        if isinstance(val, bytes):
                            val = val.decode('utf-8', errors='ignore').strip()

                        # 类型转换：int 字段转整数，bool 字段转布尔
                        if field[1] == 2:
                            try:
                                val = int(val)
                            except Exception:
                                val = 0
                        elif field[1] == 3:
                            val = str(val).strip().lower() in ('1', 'true', 't', 'yes', 'y')

                        row.append(val)

                    self.record_list.append(tuple(row))

    @staticmethod
    def _to_text(value):
        """将值转为文本字符串"""
        return str(value)

    @staticmethod
    def _to_bool(value):
        """将值转为布尔"""
        return str(value).strip().lower() in ('1', 'true', 't', 'yes', 'y')

    # ------------------------------
    # 返回所有记录（含已删除的）
    # ------------------------------
    def getRecord(self):
        return self.record_list

    # ------------------------------
    # 返回有效记录（未删除的）
    # ------------------------------
    def get_valid_records(self):
        return [r for i, r in enumerate(self.record_list) if not self.deleted_flags[i]]

    # ------------------------------
    # 插入一行记录，直接写盘
    # input: insert_record - 字段值列表（字符串形式）
    # output: True or False
    # ------------------------------
    def insert_record(self, insert_record):

        if len(insert_record) != len(self.field_name_list):
            return False

        tmp = []

        for i in range(len(self.field_name_list)):
            insert_record[i] = insert_record[i].strip()
            f = self.field_name_list[i]

            # 字符串/变长字符串字段：检查长度
            if f[1] in [0, 1]:
                if len(insert_record[i]) > f[2]:
                    return False
                tmp.append(insert_record[i])

            # 整数字段：尝试转换
            elif f[1] == 2:
                try:
                    tmp.append(int(insert_record[i]))
                except Exception:
                    return False

            # 布尔字段：转换
            elif f[1] == 3:
                tmp.append(self._to_bool(insert_record[i]))

            # 右对齐填充到字段定义长度
            pad_len = f[2] - len(insert_record[i])
            if pad_len < 0:
                return False
            insert_record[i] = ' ' * pad_len + insert_record[i]

        # 拼接所有字段值为一个字符串
        inputstr = ''.join(insert_record)

        # 更新内存
        self.record_list.append(tuple(tmp))
        self.deleted_flags.append(False)

        # 计算记录大小
        record_content_len = len(inputstr)
        record_head_len = struct.calcsize('!?ii10s')
        record_len = record_head_len + record_content_len

        # 计算每个数据块最多能存多少条记录
        MAX_RECORD_NUM = (BLOCK_SIZE - struct.calcsize('!ii')) // (record_len + struct.calcsize('!i'))
        if MAX_RECORD_NUM <= 0:
            return False

        # 确定记录写入位置（当前块满则新建块）
        if not self.record_Position:
            self.data_block_num += 1
            self.record_Position.append((1, 0))
        else:
            last = self.record_Position[-1]
            if last[1] == MAX_RECORD_NUM - 1:
                self.data_block_num += 1
                self.record_Position.append((last[0] + 1, 0))
            else:
                self.record_Position.append((last[0], last[1] + 1))

        blk, idx = self.record_Position[-1]

        # 写 block 0 头部（更新 data_block_num）
        self.f_handle.seek(0)
        self.f_handle.write(struct.pack('!ii', 0, self.data_block_num))

        # 写数据块头部
        self.f_handle.seek(BLOCK_SIZE * blk)
        self.f_handle.write(struct.pack('!ii', blk, idx + 1))

        # 写记录偏移量
        offset_pos = struct.calcsize('!ii') + idx * struct.calcsize('!i')
        begin = BLOCK_SIZE - (idx + 1) * record_len

        self.f_handle.seek(BLOCK_SIZE * blk + offset_pos)
        self.f_handle.write(struct.pack('!i', begin))

        # 写记录（头 + 内容）
        self.f_handle.seek(BLOCK_SIZE * blk + begin)

        buf = ctypes.create_string_buffer(record_len)
        struct.pack_into('!?ii10s', buf, 0,
                         False, 0, record_content_len,
                         b'2026-01-01')
        struct.pack_into(f'!{record_content_len}s',
                         buf, record_head_len,
                         inputstr.encode('utf-8'))

        self.f_handle.write(buf.raw)
        self.f_handle.flush()

        return True

    # ------------------------------
    # 按字段条件标记删除行，压缩写回
    # input:
    #   field_name: str, 条件字段名
    #   value: str, 条件值
    # ------------------------------
    def delete_by_condition(self, field_name, value):
        field_name = field_name.strip()
        field_names = [f[0].strip() for f in self.field_name_list]

        if field_name not in field_names:
            print('Field not found!')
            return

        field_index = field_names.index(field_name)

        deleted_count = 0

        # 标记匹配行为已删除
        for i, record in enumerate(self.record_list):
            if self.deleted_flags[i]:
                continue

            cell = record[field_index]
            if str(cell) == value:
                self.deleted_flags[i] = True
                deleted_count += 1

        print(f'{deleted_count} row(s) deleted.')

        # 有删除则压缩写回
        if deleted_count > 0:
            self.persist_records()

    # ------------------------------
    # 显示表中所有有效数据
    # ------------------------------
    def show_table_data(self):
        field_names = [f[0].strip() for f in self.field_name_list]

        if HAS_RICH:
            console = Console()
            table = Table(show_header=True, header_style="bold magenta", show_lines=True)
            for name in field_names:
                table.add_column(name)
            for i, r in enumerate(self.record_list):
                if not self.deleted_flags[i]:
                    table.add_row(*[self._to_text(item) for item in r])
            console.print(table)
        else:
            print('  |  '.join(field_names))
            for i, r in enumerate(self.record_list):
                if not self.deleted_flags[i]:
                    print(tuple(self._to_text(item) for item in r))

    # ------------------------------
    # 返回字段信息列表
    # ------------------------------
    def getFieldList(self):
        return self.field_name_list

    # ------------------------------
    # 析构函数：写回 block 0 头部信息，关闭文件
    # ------------------------------
    def __del__(self):
        if hasattr(self, 'f_handle') and self.f_handle:
            try:
                if hasattr(self, 'data_block_num'):
                    self.f_handle.seek(0)
                    self.f_handle.write(struct.pack('!ii', 0, self.data_block_num))
                    self.f_handle.flush()
            except Exception:
                pass
            try:
                self.f_handle.close()
            except Exception:
                pass

    # ------------------------------
    # 压缩持久化：只保留有效行，清空文件后重写
    # 策略：truncate → 重写 block 0 → 逐条插入有效记录
    # ------------------------------
    def persist_records(self):

        valid_records = self.get_valid_records()

        if not hasattr(self, 'f_handle') or self.f_handle is None:
            return

        # 1) 清空文件
        self.f_handle.seek(0)
        self.f_handle.truncate(0)
        self.f_handle.flush()

        # 2) 重置内存状态
        self.record_list = []
        self.record_Position = []
        self.deleted_flags = []
        self.data_block_num = 0
        self.block_id = 0

        # 3) 重写 block 0（表结构）
        header_buf = ctypes.create_string_buffer(BLOCK_SIZE)
        struct.pack_into('!iii', header_buf, 0, 0, 0, len(self.field_name_list))

        offset = struct.calcsize('!iii')
        for f in self.field_name_list:
            # pack 前编码为 bytes
            field_name_bytes = _pad_name(f[0]).encode('utf-8')
            struct.pack_into('!10sii', header_buf, offset, field_name_bytes, int(f[1]), int(f[2]))
            offset += struct.calcsize('!10sii')

        self.f_handle.seek(0)
        self.f_handle.write(header_buf)
        self.f_handle.flush()

        # 4) 逐条重新插入所有有效记录
        for record in valid_records:
            insert_record = []
            for val in record:
                insert_record.append(str(val))
            self.insert_record(insert_record)

    # ------------------------------
    # 按字段条件更新行（删旧插新策略）
    # input:
    #   cond_field: str, 条件字段名
    #   cond_value: str, 条件值
    #   target_field: str, 目标字段名
    #   new_value: str, 新值
    # ------------------------------
    def update_by_condition(self, cond_field, cond_value, target_field, new_value):

        field_names = [f[0].strip() for f in self.field_name_list]

        if cond_field not in field_names:
            print("Condition field not found!")
            return

        if target_field not in field_names:
            print("Target field not found!")
            return

        cond_idx = field_names.index(cond_field)
        target_idx = field_names.index(target_field)

        target_field_type = self.field_name_list[target_idx][1]
        target_field_len = self.field_name_list[target_idx][2]

        cond_value = str(cond_value).strip().strip('"').strip("'")
        new_value = str(new_value).strip().strip('"').strip("'")

        # 字符串字段长度检查
        if target_field_type in [0, 1]:
            if len(new_value) > target_field_len:
                print("Value too long!")
                return

        # 第一步：扫描所有行，收集需要更新的行
        matched_updates = []
        original_len = len(self.record_list)

        for i in range(original_len):
            if i >= len(self.deleted_flags) or self.deleted_flags[i]:
                continue

            record = self.record_list[i]
            cell = record[cond_idx]

            if str(cell) == cond_value:

                new_record = list(record)

                # 类型感知更新
                if target_field_type == 2:  # int
                    try:
                        new_record[target_idx] = int(new_value)
                    except Exception:
                        print("Type error!")
                        return

                elif target_field_type == 3:  # bool
                    new_record[target_idx] = new_value.lower() in ['true', '1', 'yes']

                else:  # string / varstr
                    new_record[target_idx] = new_value

                matched_updates.append((i, tuple(new_record)))

        if not matched_updates:
            print("0 row(s) updated.")
            return

        # 第二步：统一标记旧行为已删除
        for idx, _ in matched_updates:
            self.deleted_flags[idx] = True

        # 第三步：统一追加新行
        for _, new_record in matched_updates:
            self.record_list.append(new_record)
            self.deleted_flags.append(False)

        print(f"{len(matched_updates)} row(s) updated.")

        # 第四步：压缩持久化
        self.persist_records()
