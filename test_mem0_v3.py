import mem0
import os

m = mem0.Memory()
res_add = m.add("I love hiking", user_id="alice")
print("add type:", type(res_add))
print("add content:", res_add)

res_search = m.search("hiking", filters={"user_id": "alice"})
print("search type:", type(res_search))
print("search content:", res_search)

res_all = m.get_all(filters={"user_id": "alice"})
print("get_all type:", type(res_all))
print("get_all content:", res_all)
