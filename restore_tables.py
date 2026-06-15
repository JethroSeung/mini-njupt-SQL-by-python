#------------------------------------------------
# restore_tables.py
# 恢复三个基础表: students, courses, takes
#------------------------------------------------

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common_db
import schema_db
import storage_db
import transaction_db
import lex_db
import parser_db
import query_plan_db


def run_sql(sql_str, schema_obj):
    common_db.global_syn_tree = None
    common_db.global_logical_tree = None
    lex_db.set_lex_handle()
    parser_db.set_handle()
    common_db.global_parser.parse(sql_str)
    if common_db.global_syn_tree is not None:
        query_plan_db.execute_statement(schema_obj)


def main():
    # 清理旧文件
    for f in os.listdir('.'):
        if f.endswith('.dat') or f.endswith('.sch') or f.endswith('.log'):
            try:
                os.remove(f)
            except Exception:
                pass
    transaction_db._global_txn_manager = None

    schema_obj = schema_db.Schema()

    # 创建表
    run_sql("create table students(s_id char(10), name char(10), gender char(10), age integer)", schema_obj)
    run_sql("create table courses(c_id char(10), title char(20), semester char(10), credit integer)", schema_obj)
    run_sql("create table takes(s_id char(10), c_id char(10), score integer)", schema_obj)

    # 插入 students 数据
    run_sql("insert into students values('s01', 'Tom', 'male', 19)", schema_obj)
    run_sql("insert into students values('s02', 'Jack', 'male', 20)", schema_obj)
    run_sql("insert into students values('s03', 'Lily', 'female', 17)", schema_obj)

    # 插入 courses 数据
    run_sql("insert into courses values('c01', 'database system', 'fall', 3)", schema_obj)
    run_sql("insert into courses values('c02', 'web', 'spring', 2)", schema_obj)

    # 插入 takes 数据
    run_sql("insert into takes values('s01', 'c02', 90)", schema_obj)
    run_sql("insert into takes values('s02', 'c01', 89)", schema_obj)
    run_sql("insert into takes values('s01', 'c02', 49)", schema_obj)

    # 验证
    for table_name in ['students', 'courses', 'takes']:
        data_obj = storage_db.Storage(table_name)
        records = data_obj.get_valid_records()
        print(f'{table_name}: {len(records)} record(s)')
        for r in records:
            print(f'  {r}')
        del data_obj

    del schema_obj
    print('\nAll tables restored successfully!')


if __name__ == '__main__':
    main()
