import inspect
from pyhap.accessory import Bridge
print("--- Bridge.run ---")
print(inspect.getsource(Bridge.run))
print("--- Bridge.stop ---")
print(inspect.getsource(Bridge.stop))
