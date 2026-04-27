from common_db import BLOCK_SIZE
import struct
import os
import ctypes


class Storage(object):

    def __init__(self, tablename, skip_init=False):
        """
        input:
            tablename: table name, bytes or str
            skip_init: when True, do not ask user to create schema if file is empty
        output:
            none
        function:
            load table data from tablename.dat, and keep schema/data in memory
        """
        if isinstance(tablename, str):
            tablename = tablename.encode('utf-8')
        tablename = tablename.strip()

        self.record_list = []
        self.record_Position = []
        self.deleted_flags = []
        self.field_name_list = []
        self.open = False

        file_path = tablename + b'.dat'

        if not os.path.exists(file_path):
            print(b'table file ' + tablename + b'.dat does not exists')
            f = open(file_path, 'wb+')
            f.close()

        self.f_handle = open(file_path, 'rb+')
        print(b'table file ' + tablename + b'.dat has been opened')
        self.open = True

        self.f_handle.seek(0, os.SEEK_END)
        file_size = self.f_handle.tell()
        self.f_handle.seek(0)
        self.dir_buf = self.f_handle.read(BLOCK_SIZE)

        self.block_id = 0
        self.data_block_num = 0
        self.num_of_fields = 0

        # ------------------------------
        # 初始化 block 0
        # ------------------------------
        if file_size == 0 and not skip_init:
            self.num_of_fields = int(input("please input number of fields: "))

            self.dir_buf = ctypes.create_string_buffer(BLOCK_SIZE)
            self.block_id = 0
            self.data_block_num = 0

            struct.pack_into('!iii', self.dir_buf, 0, 0, 0, self.num_of_fields)

            offset = struct.calcsize('!iii')

            for i in range(self.num_of_fields):
                name = input(f"field {i} name: ")
                if len(name) < 10:
                    name = ' ' * (10 - len(name)) + name

                ftype = int(input("type(0 str,1 varstr,2 int,3 bool): "))
                flen = int(input("length: "))

                if isinstance(name, str):
                    name_bytes = name.encode('utf-8')
                else:
                    name_bytes = name

                self.field_name_list.append((name_bytes, ftype, flen))
                struct.pack_into('!10sii', self.dir_buf, offset, name_bytes, ftype, flen)
                offset += struct.calcsize('!10sii')

            self.f_handle.seek(0)
            self.f_handle.write(self.dir_buf)
            self.f_handle.flush()

        elif file_size == 0 and skip_init:
            # 空文件但不需要交互输入时，先保持空结构
            self.block_id = 0
            self.data_block_num = 0
            self.num_of_fields = 0
            self.field_name_list = []

        else:
            if len(self.dir_buf) < struct.calcsize('!iii'):
                raise ValueError("corrupted table file header")

            self.block_id, self.data_block_num, self.num_of_fields = struct.unpack_from('!iii', self.dir_buf, 0)

            offset = struct.calcsize('!iii')
            for i in range(self.num_of_fields):
                field = struct.unpack_from('!10sii', self.dir_buf, offset + i * struct.calcsize('!10sii'))
                self.field_name_list.append(field)

        # ------------------------------
        # 读取数据块
        # ------------------------------
        record_head_len = struct.calcsize('!?ii10s')
        record_content_len = sum(f[2] for f in self.field_name_list)

        if self.data_block_num > 0 and self.num_of_fields > 0:
            for blk in range(1, self.data_block_num + 1):
                self.f_handle.seek(BLOCK_SIZE * blk)
                buf = self.f_handle.read(BLOCK_SIZE)

                if len(buf) < struct.calcsize('!ii'):
                    continue

                block_id, record_num = struct.unpack_from('!ii', buf, 0)

                for i in range(record_num):
                    offset_pos = struct.calcsize('!ii') + i * struct.calcsize('!i')
                    if offset_pos + struct.calcsize('!i') > len(buf):
                        continue

                    offset = struct.unpack_from('!i', buf, offset_pos)[0]
                    if offset < 0 or offset + record_head_len > len(buf):
                        continue

                    # -------- 读取 record head --------
                    is_deleted, pointer, length, ts = struct.unpack_from('!?ii10s', buf, offset)
                    self.deleted_flags.append(is_deleted)
                    self.record_Position.append((blk, i))

                    # -------- 读取内容 --------
                    if record_content_len > 0 and offset + record_head_len + record_content_len <= len(buf):
                        content = struct.unpack_from(
                            f'!{record_content_len}s',
                            buf,
                            offset + record_head_len
                        )[0]
                    else:
                        content = b''

                    tmp = 0
                    row = []

                    for field in self.field_name_list:
                        val = content[tmp:tmp + field[2]].strip()
                        tmp += field[2]

                        if field[1] == 2:
                            try:
                                val = int(val)
                            except Exception:
                                val = 0
                        elif field[1] == 3:
                            if isinstance(val, bytes):
                                val = val.decode('utf-8', errors='ignore')
                            val = str(val).strip().lower() in ('1', 'true', 't', 'yes', 'y')

                        row.append(val)

                    self.record_list.append(tuple(row))

    @staticmethod
    def _to_text(value):
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='ignore')
        return str(value)

    @staticmethod
    def _to_bool(value):
        if isinstance(value, bytes):
            value = value.decode('utf-8', errors='ignore')
        return str(value).strip().lower() in ('1', 'true', 't', 'yes', 'y')

    # ------------------------------
    def getRecord(self):
        return self.record_list

    # ------------------------------
    def get_valid_records(self):
        return [r for i, r in enumerate(self.record_list) if not self.deleted_flags[i]]

    # ------------------------------
    def insert_record(self, insert_record):
        """
        input:
            insert_record: list of field values in string form
        output:
            True or False
        function:
            append one record to table and persist it to disk
        """

        if len(insert_record) != len(self.field_name_list):
            return False

        tmp = []

        for i in range(len(self.field_name_list)):
            insert_record[i] = insert_record[i].strip()
            f = self.field_name_list[i]

            if f[1] in [0, 1]:
                if len(insert_record[i]) > f[2]:
                    return False
                tmp.append(insert_record[i])

            elif f[1] == 2:
                try:
                    tmp.append(int(insert_record[i]))
                except Exception:
                    return False

            elif f[1] == 3:
                tmp.append(self._to_bool(insert_record[i]))

            pad_len = f[2] - len(insert_record[i])
            if pad_len < 0:
                return False
            insert_record[i] = ' ' * pad_len + insert_record[i]

        inputstr = ''.join(insert_record)

        self.record_list.append(tuple(tmp))
        self.deleted_flags.append(False)

        record_content_len = len(inputstr)
        record_head_len = struct.calcsize('!?ii10s')
        record_len = record_head_len + record_content_len

        MAX_RECORD_NUM = (BLOCK_SIZE - struct.calcsize('!ii')) // (record_len + struct.calcsize('!i'))
        if MAX_RECORD_NUM <= 0:
            return False

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

        # 写 block0 头部（只更新 block_id 和 data_block_num，不覆盖 num_of_fields）
        self.f_handle.seek(0)
        self.f_handle.write(struct.pack('!ii', 0, self.data_block_num))

        # 写 block head
        self.f_handle.seek(BLOCK_SIZE * blk)
        self.f_handle.write(struct.pack('!ii', blk, idx + 1))

        # 写 offset
        offset_pos = struct.calcsize('!ii') + idx * struct.calcsize('!i')
        begin = BLOCK_SIZE - (idx + 1) * record_len

        self.f_handle.seek(BLOCK_SIZE * blk + offset_pos)
        self.f_handle.write(struct.pack('!i', begin))

        # 写 record
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

    # ------------------------------全新的删除函数
    def delete_by_condition(self, field_name, value):
        """
        input:
            field_name: condition field name
            value: field value
        output:
            none
        function:
            mark matched rows deleted in memory, then persist the live rows back to disk
        """
        field_name = field_name.strip()
        field_names = [f[0].decode('utf-8', errors='ignore').strip() for f in self.field_name_list]

        if field_name not in field_names:
            print('Field not found!')
            return

        field_index = field_names.index(field_name)

        deleted_count = 0

        for i, record in enumerate(self.record_list):
            if self.deleted_flags[i]:
                continue

            cell = record[field_index]
            if isinstance(cell, bytes):
                cell = cell.decode('utf-8', errors='ignore').strip()

            if str(cell) == value:
                self.deleted_flags[i] = True
                deleted_count += 1

        print(f'{deleted_count} row(s) deleted.')

        # ⭐ 关键：持久化
        if deleted_count > 0:
            self.persist_records()

    # def delete_by_condition(self, field_name, value):
    #
    #     field_name = field_name.strip()
    #     names = [f[0].decode().strip() for f in self.field_name_list]
    #
    #     if field_name not in names:
    #         print("Field not found")
    #         return
    #
    #     idx = names.index(field_name)
    #
    #     count = 0
    #
    #     for i, r in enumerate(self.record_list):
    #
    #         if self.deleted_flags[i]:
    #             continue
    #
    #         if str(r[idx]) == value:
    #
    #             blk, rid = self.record_Position[i]
    #
    #             self.f_handle.seek(BLOCK_SIZE * blk)
    #             buf = self.f_handle.read(BLOCK_SIZE)
    #
    #             offset = struct.unpack_from(
    #                 '!i',
    #                 buf,
    #                 struct.calcsize('!ii') + rid * 4
    #             )[0]
    #
    #             # 写 is_deleted=True
    #             self.f_handle.seek(BLOCK_SIZE * blk + offset)
    #             self.f_handle.write(struct.pack('!?', True))
    #             self.f_handle.flush()
    #
    #             self.deleted_flags[i] = True
    #             count += 1
    #
    #     print(f"{count} row(s) deleted.")

    # ------------------------------
    def show_table_data(self):
        print('| '.join(self._to_text(f[0]).strip() for f in self.field_name_list))

        for i, r in enumerate(self.record_list):
            if not self.deleted_flags[i]:
                pretty_row = []
                for item in r:
                    pretty_row.append(self._to_text(item))
                print(tuple(pretty_row))

    # ------------------------------
    def getFieldList(self):
        return self.field_name_list

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

    #新增持久删除函数
    def persist_records(self):
        """
        input:
            none
        output:
            none
        function:
            compact the table file:
            1. keep only live rows
            2. truncate the original file
            3. rewrite block 0 schema header
            4. rewrite all live records back to disk
        """

        valid_records = self.get_valid_records()

        if not hasattr(self, 'f_handle') or self.f_handle is None:
            return

        # 1) 清空当前文件
        self.f_handle.seek(0)
        self.f_handle.truncate(0)
        self.f_handle.flush()

        # 2) 重置内存状态
        self.record_list = []
        self.record_Position = []
        self.deleted_flags = []
        self.data_block_num = 0
        self.block_id = 0

        # 3) 重写 block0（表结构）
        header_buf = ctypes.create_string_buffer(BLOCK_SIZE)
        struct.pack_into('!iii', header_buf, 0, 0, 0, len(self.field_name_list))

        offset = struct.calcsize('!iii')
        for f in self.field_name_list:
            field_name = f[0]
            if isinstance(field_name, str):
                field_name = field_name.encode('utf-8')
            struct.pack_into('!10sii', header_buf, offset, field_name, int(f[1]), int(f[2]))
            offset += struct.calcsize('!10sii')

        self.f_handle.seek(0)
        self.f_handle.write(header_buf)
        self.f_handle.flush()

        # 4) 用当前对象重新插入所有有效记录
        for record in valid_records:
            insert_record = []
            for val in record:
                if isinstance(val, bytes):
                    val = val.decode('utf-8', errors='ignore')
                insert_record.append(str(val))
            self.insert_record(insert_record)

    #新增update函数
    def update_by_condition(self, cond_field, cond_value, target_field, new_value):
        """
        input:
            cond_field: condition field name
            cond_value: condition value
            target_field: field to be updated
            new_value: new value for target field
        output:
            none
        function:
            update rows by a delete-then-insert strategy, but do NOT modify
            self.record_list while scanning it.
            We first collect all matched rows, then delete old ones and append
            new rows after the scan finishes.
        """

        field_names = [f[0].decode('utf-8').strip() for f in self.field_name_list]

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

        # ⭐ 长度检查（字符串字段）
        if target_field_type in [0, 1]:
            if len(new_value) > target_field_len:
                print("Value too long!")
                return

        # 先扫描，收集所有需要更新的行
        matched_updates = []
        original_len = len(self.record_list)

        for i in range(original_len):
            if i >= len(self.deleted_flags) or self.deleted_flags[i]:
                continue

            record = self.record_list[i]
            cell = record[cond_idx]

            if isinstance(cell, bytes):
                cell = cell.decode('utf-8', errors='ignore').strip()

            if str(cell) == cond_value:

                new_record = list(record)

                # ⭐ 类型感知更新
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

        # 再统一删除旧行
        for idx, _ in matched_updates:
            self.deleted_flags[idx] = True

        # 再统一追加新行
        for _, new_record in matched_updates:
            self.record_list.append(new_record)
            self.deleted_flags.append(False)

        print(f"{len(matched_updates)} row(s) updated.")

        # 最后统一持久化
        self.persist_records()