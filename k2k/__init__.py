import sys
import pymysql
from django.template.context import BaseContext

# Ensure PyMySQL acts as MySQLdb for MySQL database engine support
pymysql.install_as_MySQLdb()

# Python 3.14+ compatibility patch for Django BaseContext copy
# In Python 3.14, copy(super()) on object returns a super proxy lacking __dict__
_original_base_context_copy = getattr(BaseContext, "__copy__", None)

def _patched_base_context_copy(self):
    cls = self.__class__
    duplicate = cls.__new__(cls)
    duplicate.__dict__.update(self.__dict__)
    duplicate.dicts = self.dicts[:]
    return duplicate

BaseContext.__copy__ = _patched_base_context_copy
