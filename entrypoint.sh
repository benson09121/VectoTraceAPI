echo "Running Database Migrations"
python manage.py makemigrationos
python manage.py migrate

exec "$@"