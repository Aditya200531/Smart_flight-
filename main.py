"""
Aviation Weather Briefing System
Version: 6.0
Features:
- METAR, TAF, PIREP, SIGMET in summary
- LLM analysis in detailed reports
- Regional API error handling
"""

from flask import Flask, render_template, request, redirect, url_for, session
import requests
import os
from groq import Groq
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration - Replace with your API keys
AVWX_API_KEY = 'laKtKwL5WA0FGXNp7ViPZWuXW6MaoYj4pqF2YfALjzU'
GROQ_API_KEY = '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'
WEATHER_CLASS = {
    "VFR": {"name": "Visual Flight Rules", "severity": 1, "color": "success"},
    "MVFR": {"name": "Marginal VFR", "severity": 2, "color": "primary"},
    "IFR": {"name": "Instrument Flight Rules", "severity": 3, "color": "danger"},
    "LIFR": {"name": "Low IFR", "severity": 4, "color": "warning"},
    "UNKNOWN": {"name": "Unknown", "severity": 0, "color": "secondary"}
}

AVWX_API_BASE = "https://avwx.rest/api/"

class WeatherBriefing:
    def __init__(self):
        self.avwx_headers = {"Authorization": f"Token {AVWX_API_KEY}"}
        self.avwx_session = requests.Session()
        self.avwx_session.headers.update(self.avwx_headers)
        
        self.groq_client = Groq(api_key=GROQ_API_KEY)
        self.summary_prompt = """Analyze this aviation weather data:
METAR: {metar}
TAF: {taf}
PIREPs: {pireps_count}
SIGMETs: {sigmets_count}

Focus on flight safety considerations. Keep under 200 words."""

    def get_report(self, icao, report_type):
        try:
            response = self.avwx_session.get(
                f"{AVWX_API_BASE}{report_type}/{icao}",
                timeout=15
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                return {"error": "Access restricted"}
            if e.response.status_code == 404:
                return {"error": "Not available"}
            print(f"HTTP Error ({report_type} for {icao}): {str(e)}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"API Error ({report_type} for {icao}): {str(e)}")
            return None

    def parse_flight_plan(self, fp_str):
        try:
            elements = fp_str.split(',')
            if len(elements) % 2 != 0:
                return None
            return [(elements[i].upper().strip(), int(elements[i+1])) 
                   for i in range(0, len(elements), 2)]
        except (ValueError, IndexError) as e:
            print(f"Parse error: {str(e)}")
            return None

    def analyze_metar(self, metar):
        default_analysis = {
            'raw': 'No METAR data',
            'flight_rules': 'UNKNOWN',
            'wind_speed': 0,
            'visibility': 0,
            'ceiling': None,
            'weather': [],
            'name': WEATHER_CLASS["UNKNOWN"]["name"],
            'color': WEATHER_CLASS["UNKNOWN"]["color"]
        }
        
        if not metar or not isinstance(metar, dict):
            return default_analysis

        try:
            analysis = {
                'raw': metar.get('raw', default_analysis['raw']),
                'flight_rules': metar.get('flight_rules', 'UNKNOWN'),
                'wind_speed': metar.get('wind_speed', {}).get('value', 0),
                'visibility': metar.get('visibility', {}).get('value', 0),
                'ceiling': None,
                'weather': []
            }

            for cloud in metar.get('clouds', []):
                cloud_type = cloud.get('type', '')
                altitude = cloud.get('altitude', 0) * 100
                if cloud_type in ['BKN', 'OVC']:
                    if analysis['ceiling'] is None or altitude < analysis['ceiling']:
                        analysis['ceiling'] = altitude

            analysis['weather'] = [wx.get('repr', '') 
                                  for wx in metar.get('wx_codes', []) 
                                  if isinstance(wx, dict)]

            classification = WEATHER_CLASS.get(
                analysis['flight_rules'],
                WEATHER_CLASS["UNKNOWN"]
            )
            return {**classification, **analysis}
        
        except Exception as e:
            print(f"METAR analysis error: {str(e)}")
            return default_analysis

    def generate_llm_summary(self, data):
        try:
            prompt = self.summary_prompt.format(
                metar=data['metar'],
                taf=data['taf'],
                pireps_count=data['pireps'],
                sigmets_count=data['sigmets']
            )
            
            response = self.groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama3-8b-8192",
                temperature=0.3,
                max_tokens=400
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"LLM Error: {str(e)}")
            return "AI analysis unavailable"

    def generate_report(self, waypoints, report_type):
        report = {'summary': [], 'detailed': []}
        
        for icao, alt in waypoints:
            metar = self.get_report(icao, 'metar')
            analysis = self.analyze_metar(metar)
            taf = self.get_report(icao, 'taf')
            pireps = self.get_report(icao, 'pirep') or {}
            sigmets = self.get_report(icao, 'sigmet') or {}

            # Process counts
            pirep_count = len(pireps) if isinstance(pireps, list) else 0
            sigmet_count = len(sigmets) if isinstance(sigmets, list) else 0

            # Summary entry
            report['summary'].append({
                'icao': icao,
                'altitude': alt,
                'classification': analysis['name'],
                'color': analysis['color'],
                'metar': analysis['raw'][:60] + '...' if len(analysis['raw']) > 60 else analysis['raw'],
                'taf': taf.get('raw', 'No TAF')[:60] + '...' if taf and len(taf.get('raw', '')) > 60 else taf.get('raw', 'No TAF'),
                'pireps': pirep_count,
                'sigmets': sigmet_count,
                'wind': analysis['wind_speed'],
                'visibility': analysis['visibility'],
                'ceiling': analysis['ceiling'] or 'UNL'
            })
            
            # Detailed entry
            ai_summary = ""
            if report_type == 'detailed':
                llm_data = {
                    'metar': analysis['raw'],
                    'taf': taf.get('raw', '') if taf else '',
                    'pireps': pirep_count,
                    'sigmets': sigmet_count
                }
                ai_summary = self.generate_llm_summary(llm_data)

            report['detailed'].append({
                'icao': icao,
                'altitude': alt,
                'metar': analysis['raw'],
                'taf': taf.get('raw', 'No TAF') if taf else 'No TAF',
                'pireps': pireps if isinstance(pireps, list) else [],
                'sigmets': sigmets if isinstance(sigmets, list) else [],
                'weather': ', '.join(analysis['weather']) or 'None',
                'ai_summary': ai_summary
            })
        
        return report

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        session['flight_plan'] = request.form.get('flight_plan', '')
        session['report_type'] = request.form.get('report_type', 'summary')
        session['waypoint'] = request.form.get('waypoint', '')
        return redirect(url_for('results'))
    return render_template('index.html')

@app.route('/results')
def results():
    try:
        briefing = WeatherBriefing()
        flight_plan = session.get('flight_plan', '')
        
        if not flight_plan:
            return render_template('error.html', message="No flight plan provided")
        
        waypoints = briefing.parse_flight_plan(flight_plan)
        if not waypoints:
            return render_template('error.html', message="Invalid flight plan format")
        
        if session.get('waypoint'):
            waypoint_filter = session['waypoint'].upper().strip()
            waypoints = [wp for wp in waypoints if wp[0] == waypoint_filter]
            if not waypoints:
                return render_template('error.html', message=f"Waypoint {waypoint_filter} not found")
        
        report_data = briefing.generate_report(waypoints, session.get('report_type', 'summary'))
        
        return render_template('results.html',
            report_type=session.get('report_type', 'summary'),
            summary_data=report_data['summary'],
            detailed_data=report_data['detailed'],
            now=datetime.utcnow()
        )
    
    except Exception as e:
        return render_template('error.html', message=f"System error: {str(e)}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)