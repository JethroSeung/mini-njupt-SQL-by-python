#------------------------------------------------
# query_plan_db.py
# author: Jingyu Han  hjymail@163.com
# modified by: Ning Wang, Yidan Xu
#------------------------------------------------
#
# 查询计划模块：将语法树转换为查询计划树并执行，以及 DDL/DML 语句的执行
#
# 整体逻辑:
#   1. SELECT 查询：从语法树(AST)中提取 sel_list / from_list / where_list，
#      构建查询计划树（Proj→Filter→X→Scan），自底向上执行
#   2. DDL/DML 语句：从语法树提取参数，直接调用 schema_db / storage_db 的底层函数
#
# 查询计划树结构（以 select name from students where age=19 为例）:
#   Proj(var=['name'])           ← 投影：只保留 name 列
#     Filter(var=('age','=','19'))  ← 过滤：age=19 的行
#       X                            ← 笛卡尔积（单表时退化为扫描）
#         students                   ← 表扫描
#
# 函数分工:
#   parseNode              - 辅助类，存储从语法树提取的三个列表
#   extract_sfw_data       - 从语法树提取 sel_list / from_list / where_list
#   destruct               - 递归遍历语法树，提取数据到 parseNode
#   show                   - 递归收集叶子节点的值
#   construct_from_node    - 构建 X(笛卡尔积)节点
#   construct_where_node   - 构建 Filter(过滤)节点，无 WHERE 时跳过
#   construct_select_node  - 构建 Proj(投影)节点
#   construct_logical_tree - 入口：语法树 → 查询计划树
#   execute_logical_tree   - 入口：执行 SELECT 查询计划树，输出结果
#   _print_query_result    - 格式化输出查询结果（rich.table 或纯文本）
#
#   execute_statement      - 统一入口：根据语法树类型分发执行
#   execute_create_table   - 执行 CREATE TABLE：提取表名和字段定义，调 schema_db + storage_db
#   execute_insert         - 执行 INSERT INTO：提取表名和值列表，调 storage_db.insert_record
#   execute_delete         - 执行 DELETE FROM：提取表名，标记所有行删除，调 persist_records
#   execute_update         - 执行 UPDATE SET WHERE：提取参数，调 storage_db.update_by_condition
#   execute_drop_table     - 执行 DROP TABLE：提取表名，调 schema_db.delete_table_schema + 删文件
#
#   辅助函数:
#   _strip_quotes          - 去除字符串常量的引号
#   _collect_leaves        - 递归收集指定类型节点的叶子值
#   _collect_all_leaves    - 递归收集节点下所有叶子值
#   _collect_all_leaves_simple - 收集节点的第一个叶子值
#   _extract_field_defs    - 从 FieldDefList 节点提取所有字段定义
#   _parse_one_field_def   - 解析单个 FieldDef 节点
#------------------------------------------------

import common_db
import storage_db
import schema_db
import itertools
import os

try:
    from rich.console import Console
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# 注意：不能使用 from common_db import global_syn_tree as syn_tree
# 因为那样会在导入时绑定值，后续 global_syn_tree 更新后本地变量不会跟着变
# 必须通过 common_db.global_syn_tree 实时访问


class parseNode:
    """辅助类：存储从语法树提取的 sel_list / from_list / where_list"""
    def __init__(self):
        self.sel_list=[]
        self.from_list=[]
        self.where_list=[]

    def get_sel_list(self):
        return self.sel_list

    def get_from_list(self):
        return self.from_list

    def get_where_list(self):
        return self.where_list

    def update_sel_list(self,self_list):
        self.sel_list = self_list

    def update_from_list(self, from_list):
        self.from_list = from_list

    def update_where_list(self,where_list):
        self.where_list = where_list


#--------------------------------
# 从语法树提取 sel_list / from_list / where_list
#--------------------------------
def extract_sfw_data():
    if common_db.global_syn_tree is None:
        print('syntax tree is None')
        return [],[],()
    else:
        PN = parseNode()
        destruct(common_db.global_syn_tree,PN)
        return PN.get_sel_list(),PN.get_from_list(),PN.get_where_list()


#---------------------------------
# 递归遍历语法树，提取 SelList / FromList / Cond 的叶子值
#---------------------------------
def destruct(nodeobj,PN):
    if isinstance(nodeobj, common_db.Node):
        if nodeobj.children:
            if nodeobj.value == 'SelList':
                tmpList=[]
                show(nodeobj,tmpList)
                PN.update_sel_list(tmpList)
            elif nodeobj.value == 'FromList':
                tmpList = []
                show(nodeobj, tmpList)
                PN.update_from_list(tmpList)
            elif nodeobj.value == 'Cond':
                tmpList = []
                show(nodeobj, tmpList)
                PN.update_where_list(tmpList)
            else:
                for i in range(len(nodeobj.children)):
                    destruct(nodeobj.children[i],PN)


def show(nodeobj,tmpList):
    """递归收集叶子节点的值"""
    if isinstance(nodeobj,common_db.Node):
        if not nodeobj.children:
            tmpList.append(nodeobj.value)
        else:
            for i in range(len(nodeobj.children)):
                show(nodeobj.children[i],tmpList)
    if isinstance(nodeobj,str):
        tmpList.append(nodeobj)


#---------------------------
# 构建 X(笛卡尔积)节点
# 单表时退化为扫描
#---------------------------
def construct_from_node(from_list):
    if from_list:
        if len(from_list)==1:
            temp_node=common_db.Node(from_list[0],None)
            return common_db.Node('X',[temp_node])
        elif len(from_list)==2:
            temp_node_first=common_db.Node(from_list[0],None)
            temp_node_second=common_db.Node(from_list[1],None)
            return common_db.Node('X',[temp_node_first,temp_node_second])
        elif len(from_list)>2:
            right_node=common_db.Node(from_list[len(from_list)-1],None)
            return common_db.Node('X',[construct_from_node(from_list[0:len(from_list)-1]),right_node])


#---------------------------
# 构建 Filter(过滤)节点
# 无 WHERE 条件时直接返回 from_node（跳过过滤）
#---------------------------
def construct_where_node(from_node,where_list):
    if from_node and len(where_list)>0:
       return common_db.Node('Filter',[from_node],where_list)
    elif from_node and len(where_list)==0:
        return from_node


#---------------------------
# 构建 Proj(投影)节点
#---------------------------
def construct_select_node(wf_node,sel_list):
    if wf_node and len(sel_list)>0:
        return common_db.Node('Proj',[wf_node],sel_list)


#----------------------------------
# 构建查询计划树：语法树 → 查询计划树
#----------------------------------
def construct_logical_tree():
    if common_db.global_syn_tree:
        sel_list,from_list,where_list=extract_sfw_data()
        # 过滤掉逗号（BNF 中 COMMA 是独立 token，但不是字段名）
        sel_list=[i for i in sel_list if i!=',']
        from_list=[i for i in from_list if i!=',']
        where_list=tuple(where_list)

        from_node = construct_from_node(from_list)
        where_node = construct_where_node(from_node, where_list)
        common_db.global_logical_tree = construct_select_node(where_node, sel_list)
    else:
        print('there is no data in the syntax tree')


#----------------------------------
# 执行查询计划树，输出结果
#----------------------------------
def execute_logical_tree():
    if not common_db.global_logical_tree:
        print('there is no query plan tree for the execution')
        return

    # 第一步：将查询计划树按层级展开到 dict_ 中
    # dict_[level] = 该层所有节点的 value 列表
    # 如果节点有 var 属性，则存储为 (value, var) 元组
    idx = 0
    dict_ = {}

    def collect_levels(node_obj, idx, dict_):
        if isinstance(node_obj, common_db.Node):
            dict_.setdefault(idx, [])
            dict_[idx].append(node_obj.value)
            if node_obj.var:
                dict_[idx][-1] = tuple((dict_[idx][-1], node_obj.var))
            if node_obj.children:
                for i in range(len(node_obj.children)):
                    collect_levels(node_obj.children[i], idx + 1, dict_)

    collect_levels(common_db.global_logical_tree, idx, dict_)
    max_idx = sorted(dict_.keys(), reverse=True)[0]

    # 辅助函数：根据字段名查找其在表中的位置和类型
    def GetFilterParam(tableName_Order, current_field, param):
        if '.' in param:
            # 带表名前缀的字段：table.field
            tableName = param.split('.')[0]
            FieldName = param.split('.')[1]
            if tableName in tableName_Order:
                TableIndex = tableName_Order.index(tableName)
            else:
                return 0, 0, 0, False
        elif len(tableName_Order) == 1:
            # 单表查询，直接匹配字段名
            TableIndex = 0
            FieldName = param
        else:
            return 0, 0, 0, False

        tmp = [x[0].strip() for x in current_field[TableIndex]]
        if FieldName in tmp:
            FieldIndex = tmp.index(FieldName)
            FieldType = current_field[TableIndex][FieldIndex][1]
            return TableIndex, FieldIndex, FieldType, True
        else:
            return 0, 0, 0, False

    # 辅助函数：去除字符串常量的引号
    def strip_quotes(val):
        if isinstance(val, str) and len(val) >= 2:
            if (val[0] == "'" and val[-1] == "'") or (val[0] == '"' and val[-1] == '"'):
                return val[1:-1]
        return val

    # 第二步：自底向上执行查询计划
    current_field = []
    current_list = []
    tableName_Order = []

    idx = max_idx

    while (idx >= 0):
        # 处理最底层：表扫描
        if idx == max_idx:
            if len(dict_[idx]) > 1:
                # 多表：笛卡尔积
                a_1 = storage_db.Storage(dict_[idx][0])
                a_2 = storage_db.Storage(dict_[idx][1])
                tableName_Order = [dict_[idx][0], dict_[idx][1]]
                current_field = [a_1.getFieldList(), a_2.getFieldList()]
                current_list = []
                for x in itertools.product(a_1.get_valid_records(), a_2.get_valid_records()):
                    current_list.append(list(x))
            else:
                # 单表扫描
                a_1 = storage_db.Storage(dict_[idx][0])
                current_list = a_1.get_valid_records()
                tableName_Order = [dict_[idx][0]]
                current_field = [a_1.getFieldList()]

        # 处理 X 节点：多表笛卡尔积
        elif 'X' in dict_[idx] and len(dict_[idx]) > 1:
            a_2 = storage_db.Storage(dict_[idx][1])
            tableName_Order.append(dict_[idx][1])
            current_field.append(a_2.getFieldList())
            tmp_List = current_list[:]
            current_list = []
            for x in itertools.product(tmp_List, a_2.get_valid_records()):
                current_list.append(list((x[0][0], x[0][1], x[1])))

        # 处理 Filter 和 Proj 节点
        elif 'X' not in dict_[idx]:
            # Filter 节点：按条件过滤行
            if 'Filter' in dict_[idx][0]:
                FilterChoice = dict_[idx][0][1]
                TableIndex, FieldIndex, FieldType, isTrue = GetFilterParam(tableName_Order, current_field,
                                                                           FilterChoice[0])
                if not isTrue:
                    print('Filter field not found:', FilterChoice[0])
                    return
                else:
                    # 根据字段类型转换条件值
                    raw_val = strip_quotes(FilterChoice[2])
                    if FieldType == 2:
                        FilterParam = int(raw_val)
                    elif FieldType == 3:
                        FilterParam = raw_val.lower() in ('true', '1', 'yes')
                    else:
                        FilterParam = raw_val

                tmp_List = current_list[:]
                current_list = []
                for tmpRecord in tmp_List:
                    if len(current_field) == 1:
                        ans = tmpRecord[FieldIndex]
                    else:
                        ans = tmpRecord[TableIndex][FieldIndex]

                    if FieldType in (0, 1):
                        ans = str(ans).strip()

                    if FilterParam == ans:
                        current_list.append(tmpRecord)

            # Proj 节点：投影指定列
            if 'Proj' in dict_[idx][0]:
                proj_list = dict_[idx][0][1]

                # 处理 select * ：展开为所有字段
                if '*' in proj_list:
                    proj_list = []
                    for ti, fields in enumerate(current_field):
                        for fi, f in enumerate(fields):
                            proj_list.append(f[0].strip())

                SelIndexList = []
                for param in proj_list:
                    TableIndex, FieldIndex, FieldType, isTrue = GetFilterParam(tableName_Order, current_field, param)
                    if not isTrue:
                        print('Projection field not found:', param)
                        return
                    SelIndexList.append((TableIndex, FieldIndex))

                # 构建输出字段名
                outPutField = []
                for xi in SelIndexList:
                    outPutField.append(
                        tableName_Order[xi[0]].strip() + '.' + current_field[xi[0]][xi[1]][0].strip())

                # 投影：只保留指定列
                tmp_List = current_list[:]
                current_list = []
                for tmpRecord in tmp_List:
                    if len(current_field) == 1:
                        tmp = [tmpRecord[x[1]] for x in SelIndexList]
                    else:
                        tmp = [tmpRecord[x[0]][x[1]] for x in SelIndexList]
                    current_list.append(tmp)

                # 输出结果
                _print_query_result(outPutField, current_list)
                return

        idx -= 1


#----------------------------------
# 格式化输出查询结果
#----------------------------------
def _print_query_result(field_names, records):
    """用 rich.table 或纯文本输出查询结果"""
    # 清理字段名：去掉表名前缀，只保留字段名
    display_names = [n.split('.')[-1] if '.' in n else n for n in field_names]

    if HAS_RICH:
        console = Console()
        table = Table(show_header=True, header_style="bold magenta", show_lines=True)
        for name in display_names:
            table.add_column(name)
        for record in records:
            table.add_row(*[str(v) for v in record])
        console.print(table)
    else:
        print('  |  '.join(display_names))
        for record in records:
            print([str(v) for v in record])


# ==================== DDL/DML 执行函数 ====================

# 辅助函数：去除字符串常量的引号
def _strip_quotes(val):
    """去除字符串常量两端的单引号"""
    if isinstance(val, str) and len(val) >= 2:
        if val[0] == "'" and val[-1] == "'":
            return val[1:-1]
    return val


# 辅助函数：从语法树中递归收集指定类型节点的叶子值
def _collect_leaves(node, target_value):
    """递归遍历语法树，收集 value == target_value 的节点的叶子值"""
    result = []
    if isinstance(node, common_db.Node):
        if node.value == target_value:
            # 收集该节点下所有叶子值
            _collect_all_leaves(node, result)
        elif node.children:
            for child in node.children:
                result.extend(_collect_leaves(child, target_value))
    return result


def _collect_all_leaves(node, result):
    """递归收集节点下所有叶子值"""
    if isinstance(node, common_db.Node):
        if not node.children and node.value not in (',', '(', ')'):
            result.append(node.value)
        elif node.children:
            for child in node.children:
                _collect_all_leaves(child, result)
    elif isinstance(node, str) and node not in (',', '(', ')'):
        result.append(node)


#----------------------------------
# 统一入口：根据语法树类型分发执行
#----------------------------------
def execute_statement(schema_obj):
    """根据语法树类型分发执行"""
    tree = common_db.global_syn_tree
    if tree is None:
        print('syntax tree is None')
        return

    stmt_node = tree.children[0]
    stmt_type = stmt_node.value

    if stmt_type == 'SFW':
        construct_logical_tree()
        execute_logical_tree()
    elif stmt_type == 'CreateTable':
        execute_create_table(schema_obj, stmt_node)
    elif stmt_type == 'Insert':
        execute_insert(stmt_node)
    elif stmt_type == 'Delete':
        execute_delete(stmt_node)
    elif stmt_type == 'Update':
        execute_update(stmt_node)
    elif stmt_type == 'DropTable':
        execute_drop_table(schema_obj, stmt_node)
    else:
        print(f'Unknown statement type: {stmt_type}')


#----------------------------------
# 执行 CREATE TABLE 语句
#----------------------------------
def execute_create_table(schema_obj, stmt_node):
    """执行 CREATE TABLE：从语法树提取表名和字段定义，创建表"""
    # 1. 提取表名（TCNAME 节点，在 CREATE/TABLE 之后）
    table_name = None
    field_defs_raw = []  # 收集 FieldDef 的原始数据

    for child in stmt_node.children:
        if isinstance(child, common_db.Node):
            if child.value == 'TCNAME' and table_name is None:
                # 第一个 TCNAME 是表名
                table_name = _collect_all_leaves_simple(child)
            elif child.value == 'FieldDefList':
                # 提取所有 FieldDef
                field_defs_raw = _extract_field_defs(child)

    if not table_name:
        print('CREATE TABLE: table name not found')
        return

    # 2. 构建 fieldList: [(field_name, field_type, field_length), ...]
    field_list = []
    for fd in field_defs_raw:
        fname = fd['name']
        if fd['type'] == 'char':
            # char(n) → type=0(str), length=n
            flen = int(fd['length'])
            field_list.append((fname, 0, flen))
        elif fd['type'] == 'integer':
            # integer → type=2(int), length=4
            field_list.append((fname, 2, 4))

    # 3. 检查表是否已存在
    if schema_obj.find_table(table_name):
        print(f'Table {table_name} already exists!')
        return

    # 4. 调 schema_obj.appendTable 写入 schema
    schema_obj.appendTable(table_name, field_list)

    # 5. 创建 Storage 对象，用 init_from_fieldlist 初始化 .dat 文件
    data_obj = storage_db.Storage(table_name, skip_init=True)
    data_obj.init_from_fieldlist(field_list)
    del data_obj

    print(f'Table {table_name} created successfully.')


def _collect_all_leaves_simple(node):
    """收集节点的第一个叶子值（用于提取表名等单一值）"""
    if isinstance(node, common_db.Node):
        if not node.children:
            return node.value
        for child in node.children:
            if isinstance(child, str):
                return child
            val = _collect_all_leaves_simple(child)
            if val:
                return val
    elif isinstance(node, str):
        return node
    return None


def _extract_field_defs(fielddeflist_node):
    """从 FieldDefList 节点提取所有字段定义"""
    defs = []
    if not isinstance(fielddeflist_node, common_db.Node):
        return defs

    for child in fielddeflist_node.children:
        if isinstance(child, common_db.Node) and child.value == 'FieldDef':
            fd = _parse_one_field_def(child)
            if fd:
                defs.append(fd)
        elif isinstance(child, common_db.Node) and child.value == 'FieldDefList':
            # 递归处理嵌套的 FieldDefList
            defs.extend(_extract_field_defs(child))

    return defs


def _parse_one_field_def(fielddef_node):
    """解析单个 FieldDef 节点，返回 {'name': ..., 'type': ..., 'length': ...}"""
    # 检查子节点中是否有 CHAR 或 INTEGER 关键字节点
    has_char = False
    has_integer = False
    for child in fielddef_node.children:
        if isinstance(child, common_db.Node):
            if child.value == 'CHAR':
                has_char = True
            elif child.value == 'INTEGER':
                has_integer = True

    # 收集所有叶子值
    leaves = []
    _collect_all_leaves(fielddef_node, leaves)
    # 过滤掉括号、逗号和类型关键字
    leaves = [l for l in leaves if l not in ('(', ')', ',', 'CHAR', 'INTEGER')]

    if has_integer:
        # integer 类型：只有字段名
        return {'name': leaves[0], 'type': 'integer', 'length': None}
    elif has_char and len(leaves) >= 2:
        # char 类型：字段名 + 长度
        return {'name': leaves[0], 'type': 'char', 'length': leaves[1]}

    return None


#----------------------------------
# 执行 INSERT INTO 语句
#----------------------------------
def execute_insert(stmt_node):
    """执行 INSERT INTO ... VALUES ...：从语法树提取表名和值列表，插入数据"""
    # 1. 提取表名
    table_name = None
    values = []

    for child in stmt_node.children:
        if isinstance(child, common_db.Node):
            if child.value == 'TCNAME' and table_name is None:
                table_name = _collect_all_leaves_simple(child)
            elif child.value == 'ValueList':
                # 收集所有 CONSTANT 叶子值
                _collect_all_leaves(child, values)

    if not table_name:
        print('INSERT: table name not found')
        return

    # 2. 去除字符串值的引号
    values = [_strip_quotes(v) for v in values]

    # 3. 创建 Storage 对象，插入记录
    try:
        data_obj = storage_db.Storage(table_name)
        if data_obj.insert_record(values):
            print('1 row inserted.')
        else:
            print('Insert failed: value type or length mismatch.')
        del data_obj
    except Exception as e:
        print(f'Insert error: {e}')


#----------------------------------
# 执行 DELETE FROM 语句
#----------------------------------
def execute_delete(stmt_node):
    """执行 DELETE FROM ...：从语法树提取表名，删除表中所有数据"""
    # 1. 提取表名
    table_name = None
    for child in stmt_node.children:
        if isinstance(child, common_db.Node) and child.value == 'TCNAME':
            table_name = _collect_all_leaves_simple(child)
            break

    if not table_name:
        print('DELETE: table name not found')
        return

    # 2. 创建 Storage 对象，标记所有行为已删除，压缩写回
    try:
        data_obj = storage_db.Storage(table_name)
        # 标记所有行为已删除
        count = 0
        for i in range(len(data_obj.deleted_flags)):
            if not data_obj.deleted_flags[i]:
                data_obj.deleted_flags[i] = True
                count += 1
        data_obj.persist_records()
        del data_obj
        print(f'{count} row(s) deleted.')
    except Exception as e:
        print(f'Delete error: {e}')


#----------------------------------
# 执行 UPDATE SET WHERE 语句
#----------------------------------
def execute_update(stmt_node):
    """执行 UPDATE ... SET ... WHERE ...：从语法树提取参数，更新数据"""
    # 语法树结构：Update → [UPDATE, TCNAME(表名), SET, TCNAME(目标字段), =, CONSTANT(新值), WHERE, TCNAME(条件字段), =, CONSTANT(条件值)]
    table_name = None
    set_field = None
    set_value = None
    where_field = None
    where_value = None

    tcname_count = 0
    constant_count = 0

    for child in stmt_node.children:
        if isinstance(child, common_db.Node):
            if child.value == 'TCNAME':
                val = _collect_all_leaves_simple(child)
                if tcname_count == 0:
                    table_name = val
                elif tcname_count == 1:
                    set_field = val
                elif tcname_count == 2:
                    where_field = val
                tcname_count += 1
            elif child.value == 'CONSTANT':
                val = _collect_all_leaves_simple(child)
                val = _strip_quotes(val)
                if constant_count == 0:
                    set_value = val
                elif constant_count == 1:
                    where_value = val
                constant_count += 1

    if not table_name:
        print('UPDATE: table name not found')
        return

    # 调用 storage_db 的 update_by_condition
    try:
        data_obj = storage_db.Storage(table_name)
        data_obj.update_by_condition(where_field, where_value, set_field, set_value)
        del data_obj
    except Exception as e:
        print(f'Update error: {e}')


#----------------------------------
# 执行 DROP TABLE 语句
#----------------------------------
def execute_drop_table(schema_obj, stmt_node):
    """执行 DROP TABLE ...：从语法树提取表名，删除表结构和数据文件"""
    # 1. 提取表名
    table_name = None
    for child in stmt_node.children:
        if isinstance(child, common_db.Node) and child.value == 'TCNAME':
            table_name = _collect_all_leaves_simple(child)
            break

    if not table_name:
        print('DROP TABLE: table name not found')
        return

    # 2. 从 schema 中删除表结构
    if schema_obj.find_table(table_name):
        if schema_obj.delete_table_schema(table_name):
            # 3. 删除 .dat 文件
            file_path = table_name.strip() + '.dat'
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f'Table {table_name} dropped successfully.')
            else:
                print(f'Table {table_name} dropped (data file not found).')
        else:
            print(f'Failed to drop table {table_name}.')
    else:
        print(f'Table {table_name} does not exist.')
