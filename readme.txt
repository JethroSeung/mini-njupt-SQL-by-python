NJUPTSQL - 数据库管理系统原型
班级：B230419班
组员：B23041916宋嘉晟、B23041919张宁佳

运行环境
- Python 3.12.3
- ply   (pip install ply) — 词法分析和语法分析
- rich  (pip install rich) — 终端美化输出（可选，但很推荐安装，因为我们花了不少时间美化。未安装则自动降级为纯文本）

运行方式
1. 启动交互式界面：
   python main_db.py

2. 运行事务持久性测试（该脚本会清除原有的三张表）：
   python test_exp3.py

3. 恢复三张基础表（students、courses、takes）：
   python restore_tables.py

项目结构
main_db.py          - 主入口，交互式菜单
common_db.py        - 全局常量（BLOCK_SIZE）和语法树节点类 Node
schema_db.py        - 表模式存储（all.sch）
storage_db.py       - 表数据存储（*.dat）
head_db.py          - 模式内存缓存（Header 类）
lex_db.py           - SQL 词法分析器（基于 PLY）
parser_db.py        - SQL 语法分析器（基于 PLY）
query_plan_db.py    - 查询计划生成与执行
transaction_db.py   - 事务管理器（前像/后像/崩溃恢复）
node_db.py          - 语法树节点辅助定义
test_exp3.py        - 事务持久性测试脚本
restore_tables.py   - 基础数据恢复脚本

支持的 SQL：
- SELECT 字段列表 FROM 表名 [WHERE 字段=值]
- CREATE TABLE 表名 (字段定义, ...)
- INSERT INTO 表名 VALUES (值, ...)
- DELETE FROM 表名
- UPDATE 表名 SET 字段=值 WHERE 字段=值
- DROP TABLE 表名

数据文件
all.sch             - 所有表的模式信息
*.dat               - 各表的数据文件（每张表一个）
before_image.dat    - 前像日志（事务持久性）
after_image.dat     - 后像日志（事务持久性）
transaction.log     - ATT/CTT 事务状态日志（事务持久性）
parser.out          - PLY 自动生成的调试文件（可删除）
