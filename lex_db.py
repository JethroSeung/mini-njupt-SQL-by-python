#-------------------------------
# lex_db.py
# author: Jingyu Han hjymail@163.com
# modified by: Ning Wang, Yidan Xu
#--------------------------------------------
#
# 词法分析模块：将 SQL 字符串拆分为 token 序列
#
# 整体逻辑:
#   输入一条 SQL 语句（如 select name from students where age=19），
#   逐字符扫描，根据正则规则识别出各个 token。
#
# 定义的 tokens:
#   SELECT   - 关键字 select
#   FROM     - 关键字 from
#   WHERE    - 关键字 where
#   AND      - 关键字 and
#   STAR     - 星号 *（用于 select *）
#   TCNAME   - 表名/字段名（标识符）
#   EQX      - 等号 =
#   COMMA    - 逗号 ,
#   CONSTANT - 常量值（数字或字符串）
#   SPACE    - 空白字符（忽略）
#
# 函数分工:
#   t_SELECT    - 识别 select 关键字
#   t_FROM      - 识别 from 关键字
#   t_WHERE     - 识别 where 关键字
#   t_AND       - 识别 and 关键字
#   t_STAR      - 识别 * 符号
#   t_TCNAME    - 识别标识符（表名/字段名）
#   t_COMMA     - 识别逗号
#   t_EQX       - 识别等号
#   t_CONSTANT  - 识别常量（数字或单引号字符串）
#   t_SPACE     - 忽略空白字符
#   t_error     - 错误处理
#   set_lex_handle - 创建全局词法分析器对象
#-------------------------------
import ply.lex as lex
import common_db

tokens=('SELECT','FROM','WHERE','AND','STAR','TCNAME','EQX','COMMA','CONSTANT','SPACE')

# 关键字优先匹配（PLY 按函数定义顺序匹配）
def t_SELECT(t):
    r'select'
    return t

def t_FROM(t):
    r'from'
    return t

def t_WHERE(t):
    r'where'
    return t

def t_AND(t):
    r'and'
    return t

# 星号 *（用于 select *）
def t_STAR(t):
    r'\*'
    return t

# 标识符：字母或下划线开头，后跟字母/数字/下划线
# 注意：关键字（select/from/where/and）优先匹配，不会误判为 TCNAME
def t_TCNAME(t):
    r'[A-Za-z_]\w*'
    return t

def t_COMMA(t):
    r','
    return t

def t_EQX(t):
    r'='
    return t

# 常量：数字 或 单引号括起来的字符串
# 支持 'database system' 等带空格的字符串
def t_CONSTANT(t):
    r"\d+|'[^']*'"
    return t

# 空白字符：忽略
def t_SPACE(t):
    r'\s+'
    pass

#--------------------------
# 错误处理
#------------------------
def t_error(t):
    print(f'Illegal character: {t.value[0]}')
    t.lexer.skip(1)

#------------------------------------------
# 创建全局词法分析器对象，存入 common_db.global_lexer
#-------------------------------------------
def set_lex_handle():
    common_db.global_lexer=lex.lex()
    if common_db.global_lexer is None:
        print ('wrong when the global_lex is created')
