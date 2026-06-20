#------------------------------------------------
# test_exp3.py
# 事务持久性测试脚本
# 该脚本可以独立运行
#
# 测试场景:
#   0. 程序启动（all.sch 不存在时自动创建）
#   1. 正常建表 + 插入 + 查询
#   2. 正常更新 + 提交后数据持久
#   3. 模拟崩溃：提交后重启，数据仍在（Redo）
#   4. 模拟崩溃：未提交事务重启，数据被撤销（Undo）
#   5. 前像/后像文件格式验证
#------------------------------------------------

import os
import sys
import struct
import traceback

# 确保从项目根目录导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common_db
import schema_db
import storage_db
import transaction_db
import lex_db
import parser_db
import query_plan_db


# ============ 辅助函数 ============

def cleanup_all():
    """清理所有数据文件，确保测试环境干净"""
    import gc
    # 强制垃圾回收，确保旧对象的 __del__ 先执行完
    gc.collect()
    for f in os.listdir('.'):
        if f.endswith('.dat') or f.endswith('.sch') or f.endswith('.log'):
            try:
                os.remove(f)
            except Exception:
                pass
    # 重置全局事务管理器
    transaction_db._global_txn_manager = None


def run_sql(sql_str, schema_obj):
    """执行一条 SQL 语句"""
    common_db.global_syn_tree = None
    common_db.global_logical_tree = None
    lex_db.set_lex_handle()
    parser_db.set_handle()
    common_db.global_parser.parse(sql_str)
    if common_db.global_syn_tree is not None:
        query_plan_db.execute_statement(schema_obj)


def get_records(table_name):
    """获取表中所有有效记录"""
    data_obj = storage_db.Storage(table_name)
    records = data_obj.get_valid_records()
    del data_obj
    return records


def close_txn_mgr():
    """安全关闭全局事务管理器的文件句柄"""
    txn_mgr = transaction_db._global_txn_manager
    if txn_mgr is not None:
        if hasattr(txn_mgr, 'before_f') and txn_mgr.before_f:
            try:
                txn_mgr.before_f.close()
            except Exception:
                pass
        if hasattr(txn_mgr, 'after_f') and txn_mgr.after_f:
            try:
                txn_mgr.after_f.close()
            except Exception:
                pass
    transaction_db._global_txn_manager = None


# ============ 测试用例 ============

def test_program_startup():
    """测试0: 程序启动（all.sch 不存在时自动创建）"""
    print('\n' + '='*60)
    print('TEST 0: Program startup (all.sch auto-creation)')
    print('='*60)

    cleanup_all()

    # all.sch 不存在，Schema() 应自动创建
    schema_obj = schema_db.Schema()
    assert os.path.exists('all.sch'), 'all.sch should be auto-created'
    assert len(schema_obj.get_table_name_list()) == 0, 'Should have 0 tables initially'
    print('  PASS: Schema() auto-creates all.sch when missing')

    # 事务管理器也应正常初始化
    txn_mgr = transaction_db.get_transaction_manager()
    assert txn_mgr is not None, 'TransactionManager should be created'
    print('  PASS: TransactionManager initialized')

    del schema_obj
    print('TEST 0 PASSED\n')


def test_normal_create_insert_select():
    """测试1: 正常建表 + 插入 + 查询"""
    print('\n' + '='*60)
    print('TEST 1: Normal create table + insert + select')
    print('='*60)

    cleanup_all()
    schema_obj = schema_db.Schema()

    # 创建表
    run_sql("create table students(s_id char(10), name char(10), gender char(10), age integer)", schema_obj)
    assert schema_obj.find_table('students'), 'Table students should exist'
    print('  PASS: Table students created')

    # 插入记录
    run_sql("insert into students values('s01', 'Tom', 'male', 19)", schema_obj)
    run_sql("insert into students values('s02', 'Jack', 'male', 20)", schema_obj)
    run_sql("insert into students values('s03', 'Lily', 'female', 17)", schema_obj)

    # 验证记录存在
    records = get_records('students')
    assert len(records) == 3, f'Expected 3 records, got {len(records)}'
    print(f'  PASS: 3 records inserted and committed')

    # 验证事务管理器状态
    txn_mgr = transaction_db.get_transaction_manager()
    assert len(txn_mgr.att) == 0, 'ATT should be empty after commit'
    print('  PASS: ATT is empty after all commits')

    # SELECT 查询
    common_db.global_syn_tree = None
    common_db.global_logical_tree = None
    lex_db.set_lex_handle()
    parser_db.set_handle()
    common_db.global_parser.parse("select name from students where age=19")
    if common_db.global_syn_tree is not None:
        query_plan_db.construct_logical_tree()
        query_plan_db.execute_logical_tree()
    print('  PASS: SELECT query executed')

    del schema_obj
    print('TEST 1 PASSED\n')


def test_normal_update_and_commit():
    """测试2: 正常更新 + 提交后数据持久"""
    print('\n' + '='*60)
    print('TEST 2: Normal update + commit -> data persists')
    print('='*60)

    cleanup_all()
    schema_obj = schema_db.Schema()

    # 创建表并插入
    run_sql("create table t2(a char(10), b integer)", schema_obj)
    run_sql("insert into t2 values('alpha', 10)", schema_obj)
    run_sql("insert into t2 values('beta', 20)", schema_obj)

    # 更新
    run_sql("update t2 set a = 'gamma' where b = 10", schema_obj)

    # 验证更新结果
    records = get_records('t2')
    assert len(records) == 2, f'Expected 2 records, got {len(records)}'
    found_gamma = any('gamma' in str(r) for r in records)
    assert found_gamma, 'Updated value "gamma" not found'
    print('  PASS: Update committed successfully')

    del schema_obj
    print('TEST 2 PASSED\n')


def test_crash_after_commit_redo():
    """测试3: 模拟崩溃 - 提交后重启，数据仍在（Redo）"""
    print('\n' + '='*60)
    print('TEST 3: Crash after commit -> Redo on recovery')
    print('='*60)

    cleanup_all()
    schema_obj = schema_db.Schema()

    # 创建表并插入（会自动提交）
    run_sql("create table t3(a char(10), b integer)", schema_obj)
    run_sql("insert into t3 values('persist', 100)", schema_obj)

    # 验证数据存在
    records_before = get_records('t3')
    assert len(records_before) == 1, f'Expected 1 record before crash, got {len(records_before)}'
    print('  Before crash: 1 record exists')

    # 模拟崩溃：直接丢弃对象，不正常关闭
    close_txn_mgr()
    del schema_obj

    # 重置全局事务管理器（模拟进程重启）
    transaction_db._global_txn_manager = None

    # 重启系统
    print('  Simulating system restart...')
    schema_obj2 = schema_db.Schema()
    txn_mgr = transaction_db.get_transaction_manager()
    txn_mgr.recover()

    # 验证数据仍然存在
    records_after = get_records('t3')
    assert len(records_after) == 1, f'Expected 1 record after recovery, got {len(records_after)}'
    print('  After recovery: 1 record still exists')
    print('  PASS: Committed data survived crash (Redo)')

    del schema_obj2
    print('TEST 3 PASSED\n')


def test_crash_before_commit_undo():
    """测试4: 模拟崩溃 - 未提交事务重启，数据被撤销（Undo）"""
    print('\n' + '='*60)
    print('TEST 4: Crash before commit -> Undo on recovery')
    print('='*60)

    cleanup_all()
    schema_obj = schema_db.Schema()

    # 创建表并插入一条已提交的记录
    run_sql("create table t4(a char(10), b integer)", schema_obj)
    run_sql("insert into t4 values('committed', 1)", schema_obj)

    # 验证初始数据
    records_before = get_records('t4')
    assert len(records_before) == 1
    print('  Before uncommitted insert: 1 record')

    # 模拟未提交事务：手动操作事务管理器
    txn_mgr = transaction_db.get_transaction_manager()
    txn_id = txn_mgr.begin_transaction()

    data_obj = storage_db.Storage('t4')
    # 保存前像
    for blk_id in range(data_obj.data_block_num + 1):
        block_data = data_obj.read_block(blk_id)
        txn_mgr.write_before_image('t4', blk_id, block_data)

    # 直接插入记录（绕过自动提交）
    result = data_obj.insert_record(['uncommit', '2'])
    assert result, 'insert_record should succeed'

    # 保存后像
    for blk_id in range(data_obj.data_block_num + 1):
        block_data = data_obj.read_block(blk_id)
        txn_mgr.write_after_image('t4', blk_id, block_data)

    del data_obj

    # 验证插入后数据（2条记录）
    records_mid = get_records('t4')
    assert len(records_mid) == 2, f'Expected 2 records after insert, got {len(records_mid)}'
    print('  After uncommitted insert: 2 records')

    # 模拟崩溃：直接退出，不调用 commit
    close_txn_mgr()
    del schema_obj

    # 重置全局事务管理器（模拟进程重启）
    transaction_db._global_txn_manager = None

    # 重启系统：执行恢复
    print('  Simulating system restart...')
    schema_obj2 = schema_db.Schema()
    txn_mgr2 = transaction_db.get_transaction_manager()
    txn_mgr2.recover()

    # 验证未提交的记录被撤销
    records_after = get_records('t4')
    assert len(records_after) == 1, f'Expected 1 record after undo, got {len(records_after)}'
    print('  After recovery: 1 record (uncommitted insert undone)')
    print('  PASS: Uncommitted data was rolled back (Undo)')

    del schema_obj2
    print('TEST 4 PASSED\n')


def test_image_file_format():
    """测试5: 验证前像/后像文件格式正确"""
    print('\n' + '='*60)
    print('TEST 5: Verify image file format')
    print('='*60)

    cleanup_all()
    schema_obj = schema_db.Schema()

    run_sql("create table t5(a char(10), b integer)", schema_obj)
    run_sql("insert into t5 values('format', 42)", schema_obj)

    # 检查前像文件
    assert os.path.exists('before_image.dat'), 'before_image.dat not found'
    assert os.path.exists('after_image.dat'), 'after_image.dat not found'

    # 验证文件大小是 IMAGE_RECORD_SIZE 的整数倍
    before_size = os.path.getsize('before_image.dat')
    after_size = os.path.getsize('after_image.dat')

    from transaction_db import IMAGE_RECORD_SIZE, IMAGE_HEADER_SIZE
    assert before_size % IMAGE_RECORD_SIZE == 0, \
        f'before_image.dat size {before_size} not multiple of {IMAGE_RECORD_SIZE}'
    assert after_size % IMAGE_RECORD_SIZE == 0, \
        f'after_image.dat size {after_size} not multiple of {IMAGE_RECORD_SIZE}'

    print(f'  before_image.dat: {before_size} bytes ({before_size // IMAGE_RECORD_SIZE} records)')
    print(f'  after_image.dat: {after_size} bytes ({after_size // IMAGE_RECORD_SIZE} records)')

    # 读取并验证一条记录的头部
    with open('after_image.dat', 'rb') as f:
        header = f.read(IMAGE_HEADER_SIZE)
        rec_txn_id, rec_table, rec_block_id = struct.unpack('!i20si', header)
        rec_table = rec_table.decode('utf-8').rstrip('\x00')
        block_data = f.read(common_db.BLOCK_SIZE)

        print(f'  After image record: txn_id={rec_txn_id}, table={rec_table}, block_id={rec_block_id}')
        assert len(block_data) == common_db.BLOCK_SIZE, \
            f'Block data size {len(block_data)} != {common_db.BLOCK_SIZE}'
        print('  PASS: Image file format is correct')

    del schema_obj
    print('TEST 5 PASSED\n')


# ============ 主函数 ============

if __name__ == '__main__':
    print('='*60)
    print('  Transaction Durability Test Suite')
    print('='*60)

    passed = 0
    failed = 0

    tests = [
        test_program_startup,
        test_normal_create_insert_select,
        test_normal_update_and_commit,
        test_crash_after_commit_redo,
        test_crash_before_commit_undo,
        test_image_file_format,
    ]

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f'  TEST FAILED: {e}')
            failed += 1
            traceback.print_exc()
        except Exception as e:
            print(f'  UNEXPECTED ERROR: {e}')
            failed += 1
            traceback.print_exc()

    print('\n' + '='*60)
    print(f'  Results: {passed} passed, {failed} failed')
    if failed == 0:
        print('  ALL TESTS PASSED!')
    print('='*60)

    # 清理测试文件
    cleanup_all()
