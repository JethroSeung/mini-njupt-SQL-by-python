#------------------------------------------------
# query_plan_db.py
# author: Jingyu Han  hjymail@163.com
# modified by: Ning Wang, Yidan Xu
#------------------------------------------------
#
# 查询计划模块：将语法树转换为查询计划树并执行
#
# 整体逻辑:
#   1. 从语法树(AST)中提取 sel_list / from_list / where_list
#   2. 构建查询计划树：Proj(投影) → Filter(过滤) → X(笛卡尔积) → Scan(扫描)
#   3. 自底向上执行查询计划树，返回结果
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
#   execute_logical_tree   - 入口：执行查询计划树，输出结果
#------------------------------------------------

import common_db
import storage_db
import itertools

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
