#------------------------------------------------
# transaction_db.py
# author: Ning Wang, Yidan Xu
#------------------------------------------------
#
# 事务管理模块：实现事务持久性保障
#
# 整体逻辑:
#   1. 每条 SQL (insert/update) 作为一个事务，自动 begin → execute → commit
#   2. 修改前保存前像(before_image)，修改后保存后像(after_image)
#   3. 遵循提交规则和先记后写规则：
#      - 提交规则：后像在事务提交前写入非易失存储器
#      - 先记后写规则：后像写入数据库前，先把前像写入日志
#   4. 系统重启时根据 ATT/CTT 进行崩溃恢复
#
# 核心数据结构:
#   ATT (活动事务表): {txn_id: [(table_name, block_id), ...]}
#   CTT (提交事务表): {txn_id: [(table_name, block_id), ...]}
#
# 文件格式:
#   before_image.dat / after_image.dat:
#     每条记录 = txn_id(4B) + table_name(20B) + block_id(4B) + block_data(BLOCK_SIZE)
#     总长 = 28 + 4096 = 4124 字节
#   transaction.log: 文本格式，存储 ATT/CTT
#
# 函数分工:
#   TransactionManager  - 事务管理器类
#     begin_transaction   - 开始事务，分配 txn_id，加入 ATT
#     write_before_image  - 写前像记录到 before_image.dat
#     write_after_image   - 写后像记录到 after_image.dat
#     commit_transaction  - 提交事务，ATT → CTT，持久化
#     abort_transaction   - 中止事务，从 ATT 移除
#     recover             - 崩溃恢复：Redo CTT + Undo ATT
#     _persist_att_ctt    - 持久化 ATT/CTT 到 transaction.log
#     _load_att_ctt       - 从 transaction.log 加载 ATT/CTT
#     _find_image         - 从前像/后像文件中查找指定记录
#     cleanup             - 清理日志文件（恢复完成后）
#
#   get_transaction_manager - 获取全局事务管理器实例（单例）
#------------------------------------------------

import struct
import os
from common_db import BLOCK_SIZE

# 前像/后像记录的元信息头大小: txn_id(4) + table_name(20) + block_id(4) = 28
IMAGE_HEADER_SIZE = struct.calcsize('!i20si')
# 每条记录总长: 28 + 4096 = 4124
IMAGE_RECORD_SIZE = IMAGE_HEADER_SIZE + BLOCK_SIZE

# 全局事务管理器实例
_global_txn_manager = None


def get_transaction_manager():
    """获取全局事务管理器实例（单例模式）"""
    global _global_txn_manager
    if _global_txn_manager is None:
        _global_txn_manager = TransactionManager()
    return _global_txn_manager


class TransactionManager(object):
    """事务管理器：负责事务的生命周期管理和崩溃恢复"""

    def __init__(self):
        self.att = {}       # 活动事务表: {txn_id: [(table_name, block_id), ...]}
        self.ctt = {}       # 提交事务表: {txn_id: [(table_name, block_id), ...]}
        self.current_txn_id = 0

        self.before_img_path = 'before_image.dat'
        self.after_img_path = 'after_image.dat'
        self.log_path = 'transaction.log'

        # 如果存在 transaction.log，加载 ATT/CTT
        if os.path.exists(self.log_path):
            self._load_att_ctt()

        # 打开前像/后像文件（追加模式）
        self.before_f = open(self.before_img_path, 'ab+')
        self.after_f = open(self.after_img_path, 'ab+')

    # ------------------------------------------------
    # 开始事务：分配 txn_id，加入 ATT，持久化
    # ------------------------------------------------
    def begin_transaction(self):
        self.current_txn_id += 1
        txn_id = self.current_txn_id
        self.att[txn_id] = []
        self._persist_att_ctt()
        return txn_id

    # ------------------------------------------------
    # 写前像记录到 before_image.dat
    # input:
    #   table_name: str, 表名
    #   block_id: int, 数据块编号
    #   block_data: bytes, 数据块内容（BLOCK_SIZE 字节）
    # ------------------------------------------------
    def write_before_image(self, table_name, block_id, block_data):
        if isinstance(table_name, str):
            table_name = table_name.encode('utf-8')
        # 填充/截断表名到 20 字节
        table_name = table_name[:20].ljust(20, b'\x00')

        header = struct.pack('!i20si', self.current_txn_id, table_name, block_id)
        self.before_f.write(header + block_data)
        self.before_f.flush()

        # 记录受影响的块到 ATT
        table_str = table_name.decode('utf-8').rstrip('\x00')
        if self.current_txn_id in self.att:
            entry = (table_str, block_id)
            if entry not in self.att[self.current_txn_id]:
                self.att[self.current_txn_id].append(entry)
        # 持久化 ATT/CTT，确保崩溃后能恢复
        self._persist_att_ctt()

    # ------------------------------------------------
    # 写后像记录到 after_image.dat
    # input:
    #   table_name: str, 表名
    #   block_id: int, 数据块编号
    #   block_data: bytes, 数据块内容（BLOCK_SIZE 字节）
    # ------------------------------------------------
    def write_after_image(self, table_name, block_id, block_data):
        if isinstance(table_name, str):
            table_name = table_name.encode('utf-8')
        table_name = table_name[:20].ljust(20, b'\x00')

        header = struct.pack('!i20si', self.current_txn_id, table_name, block_id)
        self.after_f.write(header + block_data)
        self.after_f.flush()

    # ------------------------------------------------
    # 提交事务：从 ATT 移到 CTT，持久化
    # 遵循提交规则：后像在提交前已写入 after_image.dat
    # ------------------------------------------------
    def commit_transaction(self):
        txn_id = self.current_txn_id
        if txn_id in self.att:
            self.ctt[txn_id] = self.att.pop(txn_id)
        self._persist_att_ctt()

    # ------------------------------------------------
    # 中止事务：从 ATT 移除（不加入 CTT）
    # ------------------------------------------------
    def abort_transaction(self):
        txn_id = self.current_txn_id
        if txn_id in self.att:
            del self.att[txn_id]
        self._persist_att_ctt()

    # ------------------------------------------------
    # 崩溃恢复：Redo CTT + Undo ATT
    # 在系统启动时调用
    # ------------------------------------------------
    def recover(self):
        self._load_att_ctt()

        if not self.att and not self.ctt:
            print('No pending transactions. Recovery not needed.')
            return

        # Redo 阶段：重做已提交事务
        if self.ctt:
            print(f'Redo phase: {len(self.ctt)} committed transaction(s)')
            for txn_id, blocks in self.ctt.items():
                for table_name, block_id in blocks:
                    after_data = self._find_image(self.after_img_path, txn_id, table_name, block_id)
                    if after_data:
                        dat_path = table_name + '.dat'
                        if os.path.exists(dat_path):
                            with open(dat_path, 'rb+') as f:
                                f.seek(block_id * BLOCK_SIZE)
                                f.write(after_data)
                                f.flush()
                            print(f'  Redo: txn={txn_id}, table={table_name}, block={block_id}')

        # Undo 阶段：撤销未提交事务
        if self.att:
            print(f'Undo phase: {len(self.att)} active transaction(s)')
            for txn_id, blocks in self.att.items():
                for table_name, block_id in blocks:
                    before_data = self._find_image(self.before_img_path, txn_id, table_name, block_id)
                    if before_data:
                        dat_path = table_name + '.dat'
                        if os.path.exists(dat_path):
                            with open(dat_path, 'rb+') as f:
                                f.seek(block_id * BLOCK_SIZE)
                                f.write(before_data)
                                f.flush()
                            print(f'  Undo: txn={txn_id}, table={table_name}, block={block_id}')

        # 恢复完成，清理
        self.att = {}
        self.ctt = {}
        self._persist_att_ctt()
        self.cleanup()
        print('Recovery completed.')

    # ------------------------------------------------
    # 从前像/后像文件中查找指定记录
    # 扫描整个文件，返回最后一条匹配的记录
    # input:
    #   file_path: str, 文件路径
    #   txn_id: int, 事务ID
    #   table_name: str, 表名
    #   block_id: int, 数据块编号
    # output:
    #   bytes or None
    # ------------------------------------------------
    def _find_image(self, file_path, txn_id, table_name, block_id):
        result = None
        if not os.path.exists(file_path):
            return result

        with open(file_path, 'rb') as f:
            while True:
                header = f.read(IMAGE_HEADER_SIZE)
                if len(header) < IMAGE_HEADER_SIZE:
                    break
                rec_txn_id, rec_table, rec_block_id = struct.unpack('!i20si', header)
                rec_table = rec_table.decode('utf-8').rstrip('\x00')
                block_data = f.read(BLOCK_SIZE)
                if len(block_data) < BLOCK_SIZE:
                    break
                # 匹配则更新结果（取最后一条，即最新的）
                if rec_txn_id == txn_id and rec_table == table_name and rec_block_id == block_id:
                    result = block_data

        return result

    # ------------------------------------------------
    # 将 ATT/CTT 持久化到 transaction.log
    # 格式:
    #   ATT
    #   txn_id table1 block1 table2 block2 ...
    #   CTT
    #   txn_id table1 block1 table2 block2 ...
    # ------------------------------------------------
    def _persist_att_ctt(self):
        with open(self.log_path, 'w') as f:
            f.write('ATT\n')
            for txn_id, blocks in self.att.items():
                parts = [str(txn_id)]
                for table_name, block_id in blocks:
                    parts.append(table_name)
                    parts.append(str(block_id))
                f.write(' '.join(parts) + '\n')
            f.write('CTT\n')
            for txn_id, blocks in self.ctt.items():
                parts = [str(txn_id)]
                for table_name, block_id in blocks:
                    parts.append(table_name)
                    parts.append(str(block_id))
                f.write(' '.join(parts) + '\n')

    # ------------------------------------------------
    # 从 transaction.log 加载 ATT/CTT
    # ------------------------------------------------
    def _load_att_ctt(self):
        self.att = {}
        self.ctt = {}

        if not os.path.exists(self.log_path):
            return

        with open(self.log_path, 'r') as f:
            lines = f.readlines()

        section = None
        for line in lines:
            line = line.strip()
            if line == 'ATT':
                section = 'att'
                continue
            elif line == 'CTT':
                section = 'ctt'
                continue
            elif not line:
                continue

            parts = line.split()
            if len(parts) < 1:
                continue

            txn_id = int(parts[0])
            blocks = []
            i = 1
            while i + 1 < len(parts):
                table_name = parts[i]
                block_id = int(parts[i + 1])
                blocks.append((table_name, block_id))
                i += 2

            if section == 'att':
                self.att[txn_id] = blocks
            elif section == 'ctt':
                self.ctt[txn_id] = blocks

        # 更新 current_txn_id 为最大的 txn_id
        all_ids = list(self.att.keys()) + list(self.ctt.keys())
        if all_ids:
            self.current_txn_id = max(all_ids)

    # ------------------------------------------------
    # 清理日志文件（恢复完成后调用）
    # 删除 before_image.dat / after_image.dat
    # 重新打开空文件为后续事务做准备
    # ------------------------------------------------
    def cleanup(self):
        if hasattr(self, 'before_f') and self.before_f:
            self.before_f.close()
        if hasattr(self, 'after_f') and self.after_f:
            self.after_f.close()

        for path in [self.before_img_path, self.after_img_path]:
            if os.path.exists(path):
                os.remove(path)

        # 清理 transaction.log（所有事务已完成，无需保留）
        if os.path.exists(self.log_path):
            os.remove(self.log_path)

        # 重新打开空文件
        self.before_f = open(self.before_img_path, 'ab+')
        self.after_f = open(self.after_img_path, 'ab+')

    # ------------------------------------------------
    # 析构函数：关闭文件句柄，若所有事务已完成则清理日志
    # ------------------------------------------------
    def __del__(self):
        # 若所有事务都已提交（ATT 为空），清理日志文件
        if hasattr(self, 'att') and not self.att:
            try:
                self.cleanup()
            except Exception:
                pass
        for attr in ('before_f', 'after_f'):
            if hasattr(self, attr):
                f = getattr(self, attr)
                if f:
                    try:
                        f.close()
                    except Exception:
                        pass
