DIR=$(dirname $0)
sqlite3 lookup.db "create table lookup(rev text, sha text);"
sqlite3 lookup.db "create unique index rev_index on lookup(rev);"

function update_from_branch() {
    echo "Updating from branch $1"
    git log $1 | sed -e 's/@/ /' | awk 'BEGIN { LAST=none } /^commit [a-fA-F0-9]*/ { LAST=$2 } /git-svn-id/ { print $3, LAST }' | python $DIR/create_insert.py | sqlite3 lookup.db
}

for branch in `git branch -a | grep remotes/origin/RELENG-10 | sort -r` ; do
    update_from_branch $branch
done

for branch in `git branch -a | grep remotes/origin/RELENG-9 | grep -v RELENG-9-7 | grep -v RELENG-9-9 | sort -r` ; do
    update_from_branch $branch
done

update_from_branch remotes/origin/RELENG-9-9
update_from_branch remotes/origin/RELENG-9-7
