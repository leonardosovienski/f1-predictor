import sqlite3
from src.data.historical_expansion import connect_shadow,coverage_report,cross_source_report,ingest_season

class Provider:
    def fetch_schedule(self, season):
        return [{'season':season,'round':1,'name':'GP','circuit':'Track','date':'2015-01-01'}]
    def fetch_results(self, season, round_):
        return [
          {'driver_id':'a','driver':'A','constructor':'X','grid':17,'position':1,'status':'Finished','dnf':False,'points':25},
          {'driver_id':'b','driver':'B','constructor':'Y','grid':17,'position':2,'status':'Finished','dnf':False,'points':18},
        ]

def test_duplicate_historical_grid_is_preserved_and_audited(tmp_path):
    conn=connect_shadow(tmp_path/'shadow.db')
    assert ingest_season(conn,Provider(),2015)=={'races':1,'results':2,'anomalies':1}
    assert conn.execute('select grid from shadow_results order by position').fetchall()==[(17,),(17,)]
    assert coverage_report(conn)=={'races':1,'results':2,'by_season':{2015:1},
      'anomalies':1,'races_without_results':0,'shadow_only':True}

def test_cross_source_audit_compares_by_date_and_driver():
    official=sqlite3.connect(':memory:')
    official.executescript('create table races(season,round,name,circuit,date); create table results(season,round,driver,position,grid);')
    official.execute("insert into races values(2024,1,'GP','Track','2024-01-01')")
    official.execute("insert into results values(2024,1,'Driver A',1,2)")
    races=[{'source_event_id':'9','scheduled_start_utc':'2024-01-01T12:00:00+00:00'}]
    results={'9':[{'driver':'Driver A','position':1,'grid':'2'}]}
    assert cross_source_report(races,results,official,season=2024)['audit_passed'] is True

def test_cross_source_audit_accepts_unique_name_with_one_day_utc_shift():
    official=sqlite3.connect(':memory:')
    official.executescript('create table races(season,round,name,circuit,date); create table results(season,round,driver,position,grid);')
    official.execute("insert into races values(2024,22,'Las Vegas Grand Prix','Las Vegas','2024-11-23')")
    official.execute("insert into results values(2024,22,'Driver A',1,1)")
    races=[{'source_event_id':'22','grand_prix':'Las Vegas Grand Prix',
            'scheduled_start_utc':'2024-11-24T06:00:00+00:00'}]
    results={'22':[{'driver':'Driver A','position':1,'grid':'1'}]}
    report=cross_source_report(races,results,official,season=2024)
    assert report['matched_races']==1 and report['audit_passed'] is True
