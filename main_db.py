# -----------------------
# main_db.py
# author: Jingyu Han   hjymail@163.com
# modified by: Ning Wang, Yidan Xu
# -----------------------------------
# This is the main loop of the program
# ---------------------------------------

import struct
import sys
import ctypes
import os

import head_db  # the main memory structure of table schema
import schema_db  # the module to process table schema
import storage_db  # the module to process the storage of instance

import query_plan_db  # for SQL clause of which data is stored in binary format
import lex_db  # for lex, where data is stored in binary format
import parser_db  # for yacc, where ddata is tored in binary format
import common_db  # the global variables, functions, constants in the program
import query_plan_db  # construct the query plan and execute it
import mega_sfw

PROMPT_STR = 'Input your choice  \n1:add a new table structure and data \n2:delete a table structure and data\
\n3:view a table structure and data \n4:delete all tables and data \n5:select from where clause\
\n6:delete a row according to field keyword \n7:update a row according to field keyword \n. to quit):\n'


# --------------------------
# the main loop, which needs further implementation
# ---------------------------

def main():
    # main loops for the whole program
    print('main function begins to execute')

    # The instance data of table is stored in binary format, which corresponds to chapter 2-8 of textbook

    schemaObj = schema_db.Schema()  # to create a schema object, which contains the schema of all tables
    dataObj = None
    choice = input(PROMPT_STR)

    while True:

        if choice == '1':  # add a new table and lines of data
            tableName = input('please enter your new table name:').strip()
            #  tableName not in all.sch
            insertFieldList = []
            if tableName not in schemaObj.get_table_name_list():
                # Create a new table
                dataObj = storage_db.Storage(tableName)

                insertFieldList = dataObj.getFieldList()

                schemaObj.appendTable(tableName, insertFieldList)  # add the table structure
            else:
                dataObj = storage_db.Storage(tableName)

                record = []
                Field_List = dataObj.getFieldList()
                for x in Field_List:
                    s = 'Input field name is: ' + str(x[0].strip()) + '  field type is: ' + str(x[1]) + \
                        ' field maximum length is: ' + str(x[2]) + '\n'
                    record.append(input(s))

                if dataObj.insert_record(record):  # add a row
                    print('OK!')
                else:
                    print('Wrong input!')

                del dataObj

            choice = input(PROMPT_STR)





        elif choice == '2':  # delete a table from schema file and data file

            table_name = input('please input the name of the table to be deleted:').strip()
            if schemaObj.find_table(table_name):
                if schemaObj.delete_table_schema(
                        table_name):  # delete the schema from the schema file
                    dataObj = storage_db.Storage(table_name)  # create an object for the data of table
                    dataObj.delete_table_data(table_name)  # delete table content from the table file
                    del dataObj

                else:
                    print('the deletion from schema file fail')


            else:
                print('there is no table ' + table_name + ' in the schema file')


            choice = input(PROMPT_STR)



        elif choice == '3':  # view the table structure and all the data

            print(schemaObj.headObj.tableNames)
            table_name = input('please input the name of the table to be displayed:').strip()
            if table_name:    #表名不为空
                if schemaObj.find_table(table_name):
                    schemaObj.viewTableStructure(table_name)  # to be implemented

                    dataObj = storage_db.Storage(table_name)  # create an object for the data of table
                    dataObj.show_table_data()  # view all the data of the table
                    del dataObj
                else:
                    print('table name is None')

            choice = input(PROMPT_STR)



        elif choice == '4':  # delete all the table structures and their data

            table_name_list = list(schemaObj.get_table_name_list())

            for table_name in table_name_list:

                file_path = table_name.strip() + '.dat'

                if os.path.exists(file_path):
                    os.remove(file_path)
                    print('Deleted file: ' + file_path)
                else:
                    print('File not found: ' + file_path)

            # 删除 schema
            schemaObj.deleteAll()

            print("All tables and data have been deleted.")

            choice = input(PROMPT_STR)


        elif choice == '5':  # process SELECT FROM WHERE clause
            print('#        Your Query is to SQL QUERY                  #')
            sql_str = input('please enter the select from where clause:')
            try:
                mega_sfw.process_sfw(sql_str)
            except Exception:
                print('WRONG SQL INPUT!')
            choice = input(PROMPT_STR)


        elif choice == '6':  # delete a line

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

            choice = input(PROMPT_STR)

        elif choice == '7':  # update

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

            choice = input(PROMPT_STR)


        elif choice == '.':
            print('main loop finishies')
            del schemaObj
            break

    print('main loop finish!')


if __name__ == '__main__':
    main()
