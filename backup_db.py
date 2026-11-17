"""One-time consistent SQLite backup; copy the resulting backup OFF the hosting volume."""
import os,sqlite3,datetime
from pathlib import Path
root=Path(os.getenv('PAVZA_DATA_DIR','.pavza-data')).resolve()
backup_dir=root/'backups';backup_dir.mkdir(parents=True,exist_ok=True)
backup=backup_dir/('pavza-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')+'.db')
with sqlite3.connect(root/'pavza.db') as source, sqlite3.connect(backup) as target:source.backup(target)
print('Backup created:',backup)
print('Download this copy to independent, private storage; same-volume backups are not disaster recovery.')
