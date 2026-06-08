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
#
# BNF 文法:
#   Query    : SFW
#   SFW      : SELECT SelList FROM FromList WHERE Cond
#            | SELECT SelList FROM FromList          （无 WHERE）
#   SelList  : TCNAME COMMA SelList
#            | TCNAME
#            | STAR                                 （select *）
#   FromList : TCNAME COMMA FromList
#            | TCNAME
#   Cond     : TCNAME EQX CONSTANT
#
# 函数分工:
#   p_expr_query            - Query → SFW，构建根节点
#   p_expr_sfw_where        - SFW → SELECT SelList FROM FromList WHERE Cond
#   p_expr_sfw_no_where     - SFW → SELECT SelList FROM FromList（无WHERE）
#   p_expr_sellist_multi    - SelList → TCNAME COMMA SelList
#   p_expr_sellist_single   - SelList → TCNAME
#   p_expr_sellist_star     - SelList → STAR
#   p_expr_fromlist_multi   - FromList → TCNAME COMMA FromList
#   p_expr_fromlist_single  - FromList → TCNAME
#   p_expr_condition        - Cond → TCNAME EQX CONSTANT
#   p_error                 - 语法错误处理
#   set_handle              - 创建全局语法分析器对象
#----------------------------------------------------
import common_db

import ply.yacc as yacc
import ply.lex as lex

from lex_db import tokens


#------------------------------
# Query → SFW
# 构建根节点，将语法树存入 common_db.global_syn_tree
#------------------------------
def p_expr_query(t):
    'Query : SFW'
    t[0]=common_db.Node('Query',[t[1]])
    common_db.global_syn_tree=t[0]

#------------------------------
# SFW → SELECT SelList FROM FromList WHERE Cond
# 带 WHERE 子句的查询
#------------------------------
def p_expr_sfw_where(t):
    'SFW : SELECT SelList FROM FromList WHERE Cond'
    t[1]=common_db.Node('SELECT',None)
    t[3]=common_db.Node('FROM',None)
    t[5]=common_db.Node('WHERE',None)

    t[0]=common_db.Node('SFW',[t[1],t[2],t[3],t[4],t[5],t[6]])

#------------------------------
# SFW → SELECT SelList FROM FromList
# 不带 WHERE 子句的查询（如 select * from students）
#------------------------------
def p_expr_sfw_no_where(t):
    'SFW : SELECT SelList FROM FromList'
    t[1]=common_db.Node('SELECT',None)
    t[3]=common_db.Node('FROM',None)

    t[0]=common_db.Node('SFW',[t[1],t[2],t[3],t[4]])

#------------------------------
# SelList → TCNAME COMMA SelList
# 多个字段用逗号分隔
#------------------------------
def p_expr_sellist_multi(t):
    'SelList : TCNAME COMMA SelList'
    t[1]=common_db.Node('TCNAME',[t[1]])
    t[2]=common_db.Node(',',None)
    t[0]=common_db.Node('SelList',[t[1],t[2],t[3]])

#------------------------------
# SelList → TCNAME
# 单个字段
#------------------------------
def p_expr_sellist_single(t):
    'SelList : TCNAME'
    t[1]=common_db.Node('TCNAME',[t[1]])
    t[0]=common_db.Node('SelList',[t[1]])

#------------------------------
# SelList → STAR
# select * 查询所有字段
#------------------------------
def p_expr_sellist_star(t):
    'SelList : STAR'
    t[1]=common_db.Node('STAR',['*'])
    t[0]=common_db.Node('SelList',[t[1]])

#------------------------------
# FromList → TCNAME COMMA FromList
# 多表查询（逗号分隔）
#------------------------------
def p_expr_fromlist_multi(t):
    'FromList : TCNAME COMMA FromList'
    t[1]=common_db.Node('TCNAME',[t[1]])
    t[2]=common_db.Node(',',None)
    t[0]=common_db.Node('FromList',[t[1],t[2],t[3]])

#------------------------------
# FromList → TCNAME
# 单表查询
#------------------------------
def p_expr_fromlist_single(t):
    'FromList : TCNAME'
    t[1]=common_db.Node('TCNAME',[t[1]])
    t[0]=common_db.Node('FromList',[t[1]])

#------------------------------
# Cond → TCNAME EQX CONSTANT
# 条件：字段名 = 常量值
#------------------------------
def p_expr_condition(t):
    'Cond : TCNAME EQX CONSTANT'
    t[1]=common_db.Node('TCNAME',[t[1]])
    t[2]=common_db.Node('=',None)
    t[3]=common_db.Node('CONSTANT',[t[3]])

    t[0]=common_db.Node('Cond',[t[1],t[2],t[3]])

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
    common_db.global_parser=yacc.yacc(write_tables=0)
    if common_db.global_parser is None:
        print ('wrong when yacc object is created')
