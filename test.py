from subprocess import CompletedProcess, call, run
from sys import stderr, stdout
result = run(["./nodos", "-w", "./workspace", "get", "--version", "1.3.0.b4244", "-y"], stdout=stdout, stderr=stderr, universal_newlines=True)
