# -----------------------
# main_db.py
# author: Jingyu Han   hjymail@163.com
# modified by: Ning Wang, Yidan Xu
# -----------------------------------
#
# 程序主入口，提供交互式菜单
#
# 整体逻辑:
#   1. 显示启动横幅 (NJUPTSQL ASCII Art)
#   2. 创建 Schema 对象（读取 all.sch，构建 Header 内存缓存）
#   3. 显示菜单，循环等待用户选择
#   4. 根据选择调用 schema_db / storage_db / lex_db / parser_db / query_plan_db 的相应功能
#   5. 用户输入 '.' 退出，触发 Schema.__del__ 将脏缓存写回磁盘
#
# 菜单选项:
#   1 - 新建表结构并插入数据（若表已存在则仅插入数据）
#   2 - 删除表结构及数据文件
#   3 - 查看表结构和数据
#   4 - 删除所有表及数据
#   5 - SELECT FROM WHERE 查询
#   6 - 按字段条件删除行
#   7 - 按字段条件更新行
#   . - 退出程序
#
# 依赖模块:
#   head_db      - Schema 的内存缓存结构 (Header 类)
#   schema_db    - 表模式的磁盘存储与内存管理 (Schema 类)
#   storage_db   - 表数据的磁盘存储与内存管理 (Storage 类)
#   common_db    - 全局常量 (BLOCK_SIZE) 和语法树节点
#   lex_db       - 词法分析：SQL 字符串 → token 序列
#   parser_db    - 语法分析：token 序列 → 语法树(AST)
#   query_plan_db - 查询计划：语法树 → 查询计划树 → 执行
# ---------------------------------------

import struct
import sys
import ctypes
import os

try:
    from rich import print as rprint
    from rich.text import Text
    from rich.table import Table
    from rich.panel import Panel
    from rich.color import Color
    from rich.style import Style
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

import head_db  # the main memory structure of table schema
import schema_db  # the module to process table schema
import storage_db  # the module to process the storage of instance

import query_plan_db  # 查询计划：语法树 → 查询计划树 → 执行
import lex_db  # 词法分析：SQL 字符串 → token 序列
import parser_db  # 语法分析：token 序列 → 语法树(AST)
import common_db  # 全局变量、函数、常量

# NJUPTSQL ASCII Art 横幅
BANNER_ART = r"""
███╗   ██╗     ██╗██╗   ██╗██████╗ ████████╗███████╗ ██████╗ ██╗
████╗  ██║     ██║██║   ██║██╔══██╗╚══██╔══╝██╔════╝██╔═══██╗██║
██╔██╗ ██║     ██║██║   ██║██████╔╝   ██║   ███████╗██║   ██║██║
██║╚██╗██║██   ██║██║   ██║██╔═══╝    ██║   ╚════██║██║▄▄ ██║██║
██║ ╚████║╚█████╔╝╚██████╔╝██║        ██║   ███████║╚██████╔╝███████╗
╚═╝  ╚═══╝ ╚════╝  ╚═════╝ ╚═╝        ╚═╝   ╚══════╝ ╚══▀▀═╝ ╚══════╝
"""

# 蓝紫渐变色（南邮配色）
GRADIENT_COLORS = [
    (0, 90, 220),    # blue
    (40, 70, 210),
    (80, 50, 200),
    (120, 40, 190),
    (160, 30, 180),
    (200, 20, 170),  # purple
]

# 菜单项
MENU_ITEMS = [
    ("1", "Add a new table structure and data"),
    ("2", "Delete a table structure and data"),
    ("3", "View a table structure and data"),
    ("4", "Delete all tables and data"),
    ("5", "Select from where clause"),
    ("6", "Delete a row according to field keyword"),
    ("7", "Update a row according to field keyword"),
    (".", "Quit"),
]


def show_menu():
    """显示操作菜单（Rich Panel 或纯文本）"""
    if HAS_RICH:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold green", width=3)
        table.add_column(style="bright_white")
        for key, desc in MENU_ITEMS:
            table.add_row(key, desc)
        rprint(Panel(table, title="[bold]NJUPTSQL Menu[/]", border_style="cyan"))
    else:
        for key, desc in MENU_ITEMS:
            print(f"  {key}: {desc}")


def show_banner():
    """显示启动横幅（蓝紫渐变色 ASCII Art）"""
    if HAS_RICH:
        lines = BANNER_ART.strip().splitlines()
        text = Text()
        for i, line in enumerate(lines):
            # 根据行位置插值颜色
            t = i / max(len(lines) - 1, 1)
            idx = t * (len(GRADIENT_COLORS) - 1)
            lo = int(idx)
            hi = min(lo + 1, len(GRADIENT_COLORS) - 1)
            frac = idx - lo
            r = int(GRADIENT_COLORS[lo][0] * (1 - frac) + GRADIENT_COLORS[hi][0] * frac)
            g = int(GRADIENT_COLORS[lo][1] * (1 - frac) + GRADIENT_COLORS[hi][1] * frac)
            b = int(GRADIENT_COLORS[lo][2] * (1 - frac) + GRADIENT_COLORS[hi][2] * frac)
            text.append(line + '\n', style=Style(color=Color.from_rgb(r, g, b), bold=True))
        text.append('\n              A Mini Database Management System\n', style=Style(color='bright_yellow', bold=True))
        rprint(text)
    else:
        print("NJUPTSQL - A Mini Database Management System")
    print()


PROMPT_STR = 'Input your choice: '


# --------------------------
# 主循环
# ---------------------------

def main():
    # 显示启动横幅
    show_banner()

    # 创建 Schema 对象：读取 all.sch，构建 Header 内存缓存
    schemaObj = schema_db.Schema()
    dataObj = None
    show_menu()
    choice = input(PROMPT_STR)

    while True:

        if choice == '1':  # 新建表结构并插入数据
            tableName = input('please enter your new table name:').strip()

            insertFieldList = []
            if tableName not in schemaObj.get_table_name_list():
                # 表不存在：创建新表（交互输入字段信息），同时写入 schema
                dataObj = storage_db.Storage(tableName)

                insertFieldList = dataObj.getFieldList()

                schemaObj.appendTable(tableName, insertFieldList)  # 将表结构加入 schema
            else:
                # 表已存在：直接插入数据
                dataObj = storage_db.Storage(tableName)

                record = []
                Field_List = dataObj.getFieldList()
                for x in Field_List:
                    s = 'Input field name is: ' + str(x[0].strip()) + '  field type is: ' + str(x[1]) + \
                        ' field maximum length is: ' + str(x[2]) + '\n'
                    record.append(input(s))

                if dataObj.insert_record(record):  # 插入一行
                    print('OK!')
                else:
                    print('Wrong input!')

                del dataObj

            show_menu()
            choice = input(PROMPT_STR)





        elif choice == '2':  # 删除表结构及数据文件

            table_name = input('please input the name of the table to be deleted:').strip()
            if schemaObj.find_table(table_name):
                if schemaObj.delete_table_schema(
                        table_name):  # 从 schema 中删除表结构
                    dataObj = storage_db.Storage(table_name)  # 创建数据对象
                    dataObj.delete_table_data(table_name)  # 删除数据文件内容
                    del dataObj

                else:
                    print('the deletion from schema file fail')


            else:
                print('there is no table ' + table_name + ' in the schema file')


            show_menu()
            choice = input(PROMPT_STR)



        elif choice == '3':  # 查看表结构和数据

            print(schemaObj.headObj.tableNames)
            table_name = input('please input the name of the table to be displayed:').strip()
            if table_name:    #表名不为空
                if schemaObj.find_table(table_name):
                    schemaObj.viewTableStructure(table_name)  # 显示表结构

                    dataObj = storage_db.Storage(table_name)  # 创建数据对象
                    dataObj.show_table_data()  # 显示表中所有数据
                    del dataObj
                else:
                    print('table name is None')

            show_menu()
            choice = input(PROMPT_STR)



        elif choice == '4':  # 删除所有表及数据

            table_name_list = list(schemaObj.get_table_name_list())

            # 逐个删除数据文件
            for table_name in table_name_list:

                file_path = table_name.strip() + '.dat'

                if os.path.exists(file_path):
                    os.remove(file_path)
                    print('Deleted file: ' + file_path)
                else:
                    print('File not found: ' + file_path)

            # 清空 schema
            schemaObj.deleteAll()

            print("All tables and data have been deleted.")

            show_menu()
            choice = input(PROMPT_STR)


        elif choice == '5':  # SELECT FROM WHERE 查询（lex→yacc→query_plan 管线）
            print('#        Your Query is to SQL QUERY                  #')
            sql_str = input('please enter the select from where clause:')
            try:
                # 重置全局语法树和查询计划树
                common_db.global_syn_tree = None
                common_db.global_logical_tree = None

                # 第1步：词法分析 + 语法分析 → 语法树(AST)
                lex_db.set_lex_handle()
                parser_db.set_handle()
                common_db.global_parser.parse(sql_str)

                if common_db.global_syn_tree is None:
                    print('SQL syntax error!')
                else:
                    # 第2步：语法树 → 查询计划树
                    query_plan_db.construct_logical_tree()

                    # 第3步：执行查询计划，输出结果
                    query_plan_db.execute_logical_tree()
            except Exception as e:
                print('WRONG SQL INPUT!', e)
            show_menu()
            choice = input(PROMPT_STR)


        elif choice == '6':  # 按字段条件删除行

            table_name = input('please input the name of the table to be deleted from:').strip()
            field_input = input('please input (fieldname=value):')

            if '=' not in field_input:
                print('Wrong format! Use field=value')
            else:
                field, value = field_input.split('=')
                field = field.strip()
                value = value.strip()

                dataObj = storage_db.Storage(table_name)
                dataObj.delete_by_condition(field, value)
                del dataObj

            show_menu()
            choice = input(PROMPT_STR)

        elif choice == '7':  # 按字段条件更新行

            print("---- UPDATE ----")

            table_name = input("table name: ").strip()

            if not table_name:
                print("Invalid table name")
                continue

            dataObj = storage_db.Storage(table_name)

            field_names = [f[0].strip() for f in dataObj.getFieldList()]

            print("Available fields:", field_names)

            cond_field = input("condition field: ").strip()
            if cond_field not in field_names:
                print("Field not found!")
                continue

            cond_value = input("condition value: ").strip()

            target_field = input("field to update: ").strip()
            if target_field not in field_names:
                print("Field not found!")
                continue

            new_value = input("new value: ").strip()

            dataObj.update_by_condition(cond_field, cond_value, target_field, new_value)

            del dataObj

            show_menu()
            choice = input(PROMPT_STR)


        elif choice == '.':  # 退出程序
            del schemaObj  # 触发 Schema.__del__，将脏缓存写回磁盘
            break

    print('main loop finish!')


if __name__ == '__main__':
    main()
