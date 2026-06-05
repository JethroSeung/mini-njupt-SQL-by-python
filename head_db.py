#---------------------------------
# head_db.py
# author: Jingyu Han    hjymail@163.com
#--------------------------------------
# the main memory structure of table schema
# 
#------------------------------------
import struct



class Header(object): 
    #------------------------
    # constructor of the class
    # input
    #   nameList    : list of triples (table_name(str), num_of_fields(int), offset_in_body(int))
    #   fieldDict   : dict {table_name(str): [(field_name(str), field_type(int), field_length(int)), ...]}
    #   inistored   : bool, whether schema data exists
    #   inLen       : number of tables
    #   off         : where the free space begins in body of the schema file
    #---------------------------------------------------------------
    def __init__(self,nameList,fieldDict,inistored, inLen, off):
        'constructor of Header'
        print ('__init__ of Header')
          
        self.isStored=inistored # whether it is stored
        self.lenOfTableNum=inLen # number of tables
        self.offsetOfBody=off
        self.tableNames=nameList
        self.tableFields=fieldDict

        print ("isStore is ",self.isStored," tableNum is ",self.lenOfTableNum," offset is ",self.offsetOfBody)
        

    #-----------------------------
    # destructor of the class
    #-------------------------------
    def __del__(self):
        print ('del Header')

        

    #-----------------------------
    # display the schema of all the tables in the schema file
    #----------------------------------------------------------
    def showTables(self):
        if self.lenOfTableNum>0:
            print ("the length of tableNames is",len(self.tableNames))
            for i in range(len(self.tableNames)):
                print(self.tableNames[i])
                table_name = self.tableNames[i][0]
                if table_name in self.tableFields:
                    print(self.tableFields[table_name])
