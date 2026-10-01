import tempfile
import unittest
from pathlib import Path
from flask_migrate import upgrade, downgrade
from sqlalchemy import text
from app import create_app
from extensions import db
from models import Event, QRScanEvent, Team


class MigrationTests(unittest.TestCase):
    def test_populated_legacy_upgrade_and_revision_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix='aiquest-migrations-') as directory:
            app=create_app({'TESTING':True,'AUTO_INIT_DB':False,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(Path(directory)/'migration.db')})
            with app.app_context():
                migrations=str(Path(__file__).resolve().parents[1]/'migrations')
                upgrade(directory=migrations,revision='c49d61f0d62a')
                db.session.execute(text("INSERT INTO round (id,number,name,status) VALUES (1,1,'QR Riddle','COMPLETED')"))
                db.session.execute(text("INSERT INTO team (id,team_id,team_name,member_1,member_2,member_3,pin_hash,status,created_at) VALUES (1,'AQ-001','Legacy','Alex','','','test-hash','READY',CURRENT_TIMESTAMP)"))
                db.session.execute(text("INSERT INTO qr_challenge (id,qr_id,secure_token,round_id,status,created_at,room) VALUES (1,'QR-07','legacy-token',1,'ACTIVE',CURRENT_TIMESTAMP,'Library')"))
                db.session.execute(text("INSERT INTO scan_log (team_id,qr_id,round_id,scan_time,answer_status,points) VALUES (1,1,1,CURRENT_TIMESTAMP,'PENDING',0)"))
                db.session.commit()
                upgrade(directory=migrations)
                self.assertEqual(Team.query.one().team_name,'Legacy')
                self.assertEqual(Team.query.one().bonus,0)
                self.assertEqual(QRScanEvent.query.one().status,'VALID')
                self.assertFalse(Event.query.one().results_published)
                db.session.remove()
                downgrade(directory=migrations,revision='c49d61f0d62a')
                self.assertEqual(db.session.execute(text('SELECT team_name FROM team')).scalar(),'Legacy')
                db.session.remove()
                upgrade(directory=migrations)
                self.assertEqual(QRScanEvent.query.count(),1)
                db.session.remove();db.engine.dispose()
