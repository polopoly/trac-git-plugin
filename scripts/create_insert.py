import sys

print "begin transaction;";
for line in sys.stdin.readlines():
    (first, second) = line.strip().split(" ")
    print "insert or replace into lookup values ('%s', '%s');" % (first, second)
print "commit transaction;"
