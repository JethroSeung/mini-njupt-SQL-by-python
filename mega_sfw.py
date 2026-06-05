from storage_db import Storage


def normalize(v):
    """统一转成可比较的 Python 值"""
    return str(v).strip()


def convert_value(value, field_type):
    """根据字段类型，把 SQL value 转换成正确类型"""
    value = value.strip().strip('"').strip("'")

    if field_type == 2:  # int
        return int(value)
    elif field_type == 3:  # bool
        return value.lower() in ["true", "1"]
    else:  # str / varstr
        return value


def process_sfw(sql):

    # --------------------
    # 预处理 SQL
    # --------------------
    sql = sql.strip()
    sql = sql.replace(" ,", ",").replace(", ", ",")
    sql = sql.replace(" =", "=").replace("= ", "=")

    sql_lower = sql.lower()

    # --------------------
    # 检查合法性
    # --------------------
    if "select" not in sql_lower or "from" not in sql_lower:
        print("Invalid SQL")
        return

    from_index = sql_lower.index("from")

    select_part = sql[6:from_index].strip()
    rest_part = sql[from_index + 4:].strip()

    # --------------------
    # 解析 columns
    # --------------------
    if select_part == "*":
        columns = None

    else:
        if "," not in select_part and " " in select_part:
            print("Invalid SELECT syntax: columns should be separated by commas")
            return

        raw_columns = select_part.split(",")

        columns = []

        for c in raw_columns:
            c = c.strip().strip('"').strip("'")  # 去引号
            if c:
                columns.append(c)

    # --------------------
    # 解析 table / where
    # --------------------
    rest_lower = rest_part.lower()

    if "where" in rest_lower:
        where_index = rest_lower.index("where")
        table_name = rest_part[:where_index].strip()
        where_part = rest_part[where_index + 5:].strip()
    else:
        table_name = rest_part.strip()
        where_part = None

    # --------------------
    # 读取数据
    # --------------------
    storage = Storage(table_name)
    records = storage.get_valid_records()
    fields = storage.getFieldList()

    field_names = [f[0].strip() for f in fields]

    # --------------------
    # WHERE 处理
    # --------------------
    if where_part:

        if "=" not in where_part:
            print("Invalid WHERE clause")
            return

        field, value = where_part.split("=")
        field = field.strip()

        if field not in field_names:
            print("Field not found:", field)
            return

        field_index = field_names.index(field)
        field_type = fields[field_index][1]

        target_value = convert_value(value, field_type)

        filtered = []

        for r in records:

            cell = normalize(r[field_index])

            try:
                if field_type == 2:  # int
                    if int(cell) == target_value:
                        filtered.append(r)

                elif field_type == 3:  # bool
                    if bool(cell) == target_value:
                        filtered.append(r)

                else:  # str
                    if str(cell) == target_value:
                        filtered.append(r)

            except:
                continue  # 防御性处理

        records = filtered

    # --------------------
    # 输出
    # --------------------
    def pretty(v):
        return normalize(v)

    if columns is None:

        print(field_names)

        for r in records:
            print([pretty(x) for x in r])

    else:

        col_index = []

        for c in columns:
            if c not in field_names:
                print("Field not found:", c)
                return
            col_index.append(field_names.index(c))

        print(columns)

        for r in records:
            row = [pretty(r[i]) for i in col_index]
            print(row)
