#-----------------------------
# parser_db.py
# author: Jingyu Han   hjymail@163.com
# modified by: Ning Wang, Yidan Xu
#-------------------------------
#
# 语法分析模块：将 token 序列构建为语法树(AST)
#
# 整体逻辑:
#   输入词法分析产生的 token 序列，
#   根据 BNF 文法规则递归下降解析，构建语法树。
#   语法树根节点存入 common_db.global_syn_tree。
#
# BNF 文法:
#   Query         : SFW
#                 | CreateTableStmt
#                 | InsertStmt
#                 | DeleteStmt
#                 | UpdateStmt
#                 | DropTableStmt
#
#   SFW           : SELECT SelList FROM FromList WHERE Cond
#                 | SELECT SelList FROM FromList
#
#   SelList       : TCNAME COMMA SelList
#                 | TCNAME
#                 | STAR
#
#   FromList      : TCNAME COMMA FromList
#                 | TCNAME
#
#   Cond          : TCNAME EQX CONSTANT
#
#   CreateTableStmt : CREATE TABLE TCNAME LPAREN FieldDefList RPAREN
#   FieldDefList  : FieldDef COMMA FieldDefList
#                 | FieldDef
#   FieldDef      : TCNAME CHAR LPAREN CONSTANT RPAREN
#                 | TCNAME INTEGER
#
#   InsertStmt    : INSERT INTO TCNAME VALUES LPAREN ValueList RPAREN
#   ValueList     : CONSTANT COMMA ValueList
#                 | CONSTANT
#
#   DeleteStmt    : DELETE FROM TCNAME
#
#   UpdateStmt    : UPDATE TCNAME SET TCNAME EQX CONSTANT WHERE TCNAME EQX CONSTANT
#
#   DropTableStmt : DROP TABLE TCNAME
#
# 函数分工:
#   p_expr_query              - Query → SFW / CreateTableStmt / InsertStmt / DeleteStmt / UpdateStmt / DropTableStmt
#   p_expr_sfw_where          - SFW → SELECT SelList FROM FromList WHERE Cond
#   p_expr_sfw_no_where       - SFW → SELECT SelList FROM FromList（无WHERE）
#   p_expr_sellist_multi      - SelList → TCNAME COMMA SelList
#   p_expr_sellist_single     - SelList → TCNAME
#   p_expr_sellist_star       - SelList → STAR
#   p_expr_fromlist_multi     - FromList → TCNAME COMMA FromList
#   p_expr_fromlist_single    - FromList → TCNAME
#   p_expr_condition          - Cond → TCNAME EQX CONSTANT
#   p_expr_create_table       - CreateTableStmt → CREATE TABLE TCNAME LPAREN FieldDefList RPAREN
#   p_expr_fielddef_list_multi- FieldDefList → FieldDef COMMA FieldDefList
#   p_expr_fielddef_list_single- FieldDefList → FieldDef
#   p_expr_fielddef_char      - FieldDef → TCNAME CHAR LPAREN CONSTANT RPAREN
#   p_expr_fielddef_integer   - FieldDef → TCNAME INTEGER
#   p_expr_insert             - InsertStmt → INSERT INTO TCNAME VALUES LPAREN ValueList RPAREN
#   p_expr_valuelist_multi    - ValueList → CONSTANT COMMA ValueList
#   p_expr_valuelist_single   - ValueList → CONSTANT
#   p_expr_delete             - DeleteStmt → DELETE FROM TCNAME
#   p_expr_update             - UpdateStmt → UPDATE TCNAME SET TCNAME EQX CONSTANT WHERE TCNAME EQX CONSTANT
#   p_expr_drop_table         - DropTableStmt → DROP TABLE TCNAME
#   p_error                   - 语法错误处理
#   set_handle                - 创建全局语法分析器对象
#----------------------------------------------------
import common_db

import ply.yacc as yacc
import ply.lex as lex

from lex_db import tokens


#------------------------------
# Query → SFW
# 构建 SELECT 查询的根节点
#------------------------------
def p_expr_query_sfw(t):
    'Query : SFW'
    t[0] = common_db.Node('Query', [t[1]])
    common_db.global_syn_tree = t[0]

#------------------------------
# Query → CreateTableStmt
# 构建 CREATE TABLE 的根节点
#------------------------------
def p_expr_query_create(t):
    'Query : CreateTableStmt'
    t[0] = common_db.Node('Query', [t[1]])
    common_db.global_syn_tree = t[0]

#------------------------------
# Query → InsertStmt
# 构建 INSERT INTO 的根节点
#------------------------------
def p_expr_query_insert(t):
    'Query : InsertStmt'
    t[0] = common_db.Node('Query', [t[1]])
    common_db.global_syn_tree = t[0]

#------------------------------
# Query → DeleteStmt
# 构建 DELETE FROM 的根节点
#------------------------------
def p_expr_query_delete(t):
    'Query : DeleteStmt'
    t[0] = common_db.Node('Query', [t[1]])
    common_db.global_syn_tree = t[0]

#------------------------------
# Query → UpdateStmt
# 构建 UPDATE SET WHERE 的根节点
#------------------------------
def p_expr_query_update(t):
    'Query : UpdateStmt'
    t[0] = common_db.Node('Query', [t[1]])
    common_db.global_syn_tree = t[0]

#------------------------------
# Query → DropTableStmt
# 构建 DROP TABLE 的根节点
#------------------------------
def p_expr_query_drop(t):
    'Query : DropTableStmt'
    t[0] = common_db.Node('Query', [t[1]])
    common_db.global_syn_tree = t[0]


# ==================== SELECT 查询 ====================

#------------------------------
# SFW → SELECT SelList FROM FromList WHERE Cond
# 带 WHERE 子句的查询
#------------------------------
def p_expr_sfw_where(t):
    'SFW : SELECT SelList FROM FromList WHERE Cond'
    t[1] = common_db.Node('SELECT', None)
    t[3] = common_db.Node('FROM', None)
    t[5] = common_db.Node('WHERE', None)
    t[0] = common_db.Node('SFW', [t[1], t[2], t[3], t[4], t[5], t[6]])

#------------------------------
# SFW → SELECT SelList FROM FromList
# 不带 WHERE 子句的查询（如 select * from students）
#------------------------------
def p_expr_sfw_no_where(t):
    'SFW : SELECT SelList FROM FromList'
    t[1] = common_db.Node('SELECT', None)
    t[3] = common_db.Node('FROM', None)
    t[0] = common_db.Node('SFW', [t[1], t[2], t[3], t[4]])

#------------------------------
# SelList → TCNAME COMMA SelList
# 多个字段用逗号分隔
#------------------------------
def p_expr_sellist_multi(t):
    'SelList : TCNAME COMMA SelList'
    t[1] = common_db.Node('TCNAME', [t[1]])
    t[2] = common_db.Node(',', None)
    t[0] = common_db.Node('SelList', [t[1], t[2], t[3]])

#------------------------------
# SelList → TCNAME
# 单个字段
#------------------------------
def p_expr_sellist_single(t):
    'SelList : TCNAME'
    t[1] = common_db.Node('TCNAME', [t[1]])
    t[0] = common_db.Node('SelList', [t[1]])

#------------------------------
# SelList → STAR
# select * 查询所有字段
#------------------------------
def p_expr_sellist_star(t):
    'SelList : STAR'
    t[1] = common_db.Node('STAR', ['*'])
    t[0] = common_db.Node('SelList', [t[1]])

#------------------------------
# FromList → TCNAME COMMA FromList
# 多表查询（逗号分隔）
#------------------------------
def p_expr_fromlist_multi(t):
    'FromList : TCNAME COMMA FromList'
    t[1] = common_db.Node('TCNAME', [t[1]])
    t[2] = common_db.Node(',', None)
    t[0] = common_db.Node('FromList', [t[1], t[2], t[3]])

#------------------------------
# FromList → TCNAME
# 单表查询
#------------------------------
def p_expr_fromlist_single(t):
    'FromList : TCNAME'
    t[1] = common_db.Node('TCNAME', [t[1]])
    t[0] = common_db.Node('FromList', [t[1]])

#------------------------------
# Cond → TCNAME EQX CONSTANT
# 条件：字段名 = 常量值
#------------------------------
def p_expr_condition(t):
    'Cond : TCNAME EQX CONSTANT'
    t[1] = common_db.Node('TCNAME', [t[1]])
    t[2] = common_db.Node('=', None)
    t[3] = common_db.Node('CONSTANT', [t[3]])
    t[0] = common_db.Node('Cond', [t[1], t[2], t[3]])


# ==================== CREATE TABLE ====================

#------------------------------
# CreateTableStmt → CREATE TABLE TCNAME LPAREN FieldDefList RPAREN
# 建表语句：表名 + 字段定义列表
#------------------------------
def p_expr_create_table(t):
    'CreateTableStmt : CREATE TABLE TCNAME LPAREN FieldDefList RPAREN'
    t[1] = common_db.Node('CREATE', None)
    t[2] = common_db.Node('TABLE', None)
    t[3] = common_db.Node('TCNAME', [t[3]])
    t[4] = common_db.Node('(', None)
    t[6] = common_db.Node(')', None)
    t[0] = common_db.Node('CreateTable', [t[1], t[2], t[3], t[4], t[5], t[6]])

#------------------------------
# FieldDefList → FieldDef COMMA FieldDefList
# 多个字段定义用逗号分隔
#------------------------------
def p_expr_fielddef_list_multi(t):
    'FieldDefList : FieldDef COMMA FieldDefList'
    t[2] = common_db.Node(',', None)
    t[0] = common_db.Node('FieldDefList', [t[1], t[2], t[3]])

#------------------------------
# FieldDefList → FieldDef
# 单个字段定义
#------------------------------
def p_expr_fielddef_list_single(t):
    'FieldDefList : FieldDef'
    t[0] = common_db.Node('FieldDefList', [t[1]])

#------------------------------
# FieldDef → TCNAME CHAR LPAREN CONSTANT RPAREN
# 字符串类型字段：如 title char(20)
#------------------------------
def p_expr_fielddef_char(t):
    'FieldDef : TCNAME CHAR LPAREN CONSTANT RPAREN'
    t[1] = common_db.Node('TCNAME', [t[1]])
    t[2] = common_db.Node('CHAR', None)
    t[3] = common_db.Node('(', None)
    t[4] = common_db.Node('CONSTANT', [t[4]])
    t[5] = common_db.Node(')', None)
    t[0] = common_db.Node('FieldDef', [t[1], t[2], t[3], t[4], t[5]])

#------------------------------
# FieldDef → TCNAME INTEGER
# 整数类型字段：如 credit integer
#------------------------------
def p_expr_fielddef_integer(t):
    'FieldDef : TCNAME INTEGER'
    t[1] = common_db.Node('TCNAME', [t[1]])
    t[2] = common_db.Node('INTEGER', None)
    t[0] = common_db.Node('FieldDef', [t[1], t[2]])


# ==================== INSERT INTO ====================

#------------------------------
# InsertStmt → INSERT INTO TCNAME VALUES LPAREN ValueList RPAREN
# 插入语句：表名 + 值列表
#------------------------------
def p_expr_insert(t):
    'InsertStmt : INSERT INTO TCNAME VALUES LPAREN ValueList RPAREN'
    t[1] = common_db.Node('INSERT', None)
    t[2] = common_db.Node('INTO', None)
    t[3] = common_db.Node('TCNAME', [t[3]])
    t[4] = common_db.Node('VALUES', None)
    t[5] = common_db.Node('(', None)
    t[7] = common_db.Node(')', None)
    t[0] = common_db.Node('Insert', [t[1], t[2], t[3], t[4], t[5], t[6], t[7]])

#------------------------------
# ValueList → CONSTANT COMMA ValueList
# 多个值用逗号分隔
#------------------------------
def p_expr_valuelist_multi(t):
    'ValueList : CONSTANT COMMA ValueList'
    t[1] = common_db.Node('CONSTANT', [t[1]])
    t[2] = common_db.Node(',', None)
    t[0] = common_db.Node('ValueList', [t[1], t[2], t[3]])

#------------------------------
# ValueList → CONSTANT
# 单个值
#------------------------------
def p_expr_valuelist_single(t):
    'ValueList : CONSTANT'
    t[1] = common_db.Node('CONSTANT', [t[1]])
    t[0] = common_db.Node('ValueList', [t[1]])


# ==================== DELETE FROM ====================

#------------------------------
# DeleteStmt → DELETE FROM TCNAME
# 删除语句：删除表中所有数据
#------------------------------
def p_expr_delete(t):
    'DeleteStmt : DELETE FROM TCNAME'
    t[1] = common_db.Node('DELETE', None)
    t[2] = common_db.Node('FROM', None)
    t[3] = common_db.Node('TCNAME', [t[3]])
    t[0] = common_db.Node('Delete', [t[1], t[2], t[3]])


# ==================== UPDATE SET WHERE ====================

#------------------------------
# UpdateStmt → UPDATE TCNAME SET TCNAME EQX CONSTANT WHERE TCNAME EQX CONSTANT
# 更新语句：UPDATE 表名 SET 目标字段=新值 WHERE 条件字段=条件值
#------------------------------
def p_expr_update(t):
    'UpdateStmt : UPDATE TCNAME SET TCNAME EQX CONSTANT WHERE TCNAME EQX CONSTANT'
    t[1] = common_db.Node('UPDATE', None)
    t[2] = common_db.Node('TCNAME', [t[2]])   # 表名
    t[3] = common_db.Node('SET', None)
    t[4] = common_db.Node('TCNAME', [t[4]])   # 目标字段
    t[5] = common_db.Node('=', None)
    t[6] = common_db.Node('CONSTANT', [t[6]]) # 新值
    t[7] = common_db.Node('WHERE', None)
    t[8] = common_db.Node('TCNAME', [t[8]])   # 条件字段
    t[9] = common_db.Node('=', None)
    t[10] = common_db.Node('CONSTANT', [t[10]]) # 条件值
    t[0] = common_db.Node('Update', [t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9], t[10]])


# ==================== DROP TABLE ====================

#------------------------------
# DropTableStmt → DROP TABLE TCNAME
# 删表语句：删除表结构和数据文件
#------------------------------
def p_expr_drop_table(t):
    'DropTableStmt : DROP TABLE TCNAME'
    t[1] = common_db.Node('DROP', None)
    t[2] = common_db.Node('TABLE', None)
    t[3] = common_db.Node('TCNAME', [t[3]])
    t[0] = common_db.Node('DropTable', [t[1], t[2], t[3]])


#------------------------------
# 语法错误处理
#------------------------------
def p_error(t):
    if t:
        print(f'Syntax error at: {t.value}')
    else:
        print('Syntax error: unexpected end of input')

#------------------------------------------
# 创建全局语法分析器对象，存入 common_db.global_parser
#---------------------------------------------
def set_handle():
    common_db.global_parser = yacc.yacc(write_tables=0)
    if common_db.global_parser is None:
        print('wrong when yacc object is created')
