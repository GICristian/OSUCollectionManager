import sys
import realm

# Wait, we might not have 'realm' module for Python.
# Let's use `strings` or a quick hexdump to find table names, or just `sqlite3`.
# Actually Realm files are not SQLite.
