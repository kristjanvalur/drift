
# switch to python 2
pipenv --rm
rm Pipfile
rm Pipfile.lock
find . -name "*.pyc" -exec rm "{}" ";"
pipenv --two
pipenv install -e "../drift-config[s3-backend,redis-backend]"
pipenv install -e ".[aws,test]"