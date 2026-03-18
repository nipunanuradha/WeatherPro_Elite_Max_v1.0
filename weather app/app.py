import secrets, smtplib, os
from flask import Flask, render_template, request, session, send_from_directory
from weather_logic import WeatherFetcher
from flight_logic import FlightFetcher
from email.mime.text import MIMEText
from twilio.rest import Client
from dotenv import load_dotenv

# load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(16))

API_KEY = os.getenv("WEATHER_API_KEY")
fetcher = WeatherFetcher(API_KEY)

FLIGHT_API_KEY = os.getenv("AVIATIONSTACK_API_KEY")
flight_fetcher = FlightFetcher(FLIGHT_API_KEY)

# Alerts Config
EMAIL_ADDR = os.getenv("EMAIL_ADDR")
EMAIL_PASS = os.getenv("EMAIL_PASS")    
TW_SID = os.getenv("TW_SID")
TW_TOKEN = os.getenv("TW_TOKEN")
TW_PHONE = os.getenv("TW_PHONE")

# PWA service Routes
@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js')

def trigger_alerts(city, rain_chance, user_email, user_phone):
    try:
        rain_chance = float(rain_chance)
    except (TypeError, ValueError):
        return

    if rain_chance > 70 and city:
        msg = f"⚠️ Alert: High Rain Chance ({rain_chance}%) in {city}!"
        if user_email and EMAIL_ADDR and EMAIL_PASS:
            try:
                mail = MIMEText(msg)
                mail['Subject'] = "Weather Alert"
                mail['From'] = EMAIL_ADDR
                mail['To'] = user_email
                with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
                    s.login(EMAIL_ADDR, EMAIL_PASS)
                    s.send_message(mail)
            except Exception:
                pass

        if user_phone and TW_SID and TW_TOKEN and TW_PHONE:
            try:
                Client(TW_SID, TW_TOKEN).messages.create(body=msg, from_=TW_PHONE, to=user_phone)
            except Exception:
                pass

@app.route('/', methods=['GET', 'POST'])
def index():
    weather_data, weather_data2 = None, None
    history_graph = []
    h_labels, h_temps = [], []
    news_articles = fetcher.fetch_weather_news()
    
    if 'history' not in session: session['history'] = []

    if request.method == 'POST':
        city = request.form.get('city')
        city2 = request.form.get('city2') # Second city input for comparison
        email = request.form.get('email')
        phone = request.form.get('phone')
        
        weather_data = fetcher.fetch_weather(city)
        if city2:
            weather_data2 = fetcher.fetch_weather(city2) # Get weather for second city if provided

        if weather_data and isinstance(weather_data, dict) and 'forecast' in weather_data and 'location' in weather_data:
            history_graph = fetcher.fetch_7day_history(city)

            rain_chance = None
            try:
                rain_chance = weather_data['forecast']['forecastday'][0]['day'].get('daily_chance_of_rain')
            except Exception:
                rain_chance = None

            trigger_alerts(city, rain_chance, email, phone)

            try:
                for hour in weather_data['forecast']['forecastday'][0]['hour']:
                    h_labels.append(hour['time'].split(' ')[1])
                    h_temps.append(hour['temp_c'])
            except Exception:
                pass

            name = weather_data['location'].get('name')
            if name:
                if name not in session['history']:
                    session['history'] = [name] + session['history'][:4]
                    session.modified = True

    return render_template('index.html', data=weather_data, data2=weather_data2, 
                           history_list=session['history'], labels=h_labels, 
                           temps=h_temps, history_graph=history_graph, news=news_articles)

@app.route('/flight', methods=['GET', 'POST'])
def flight_tracker():
    flight_data = None
    if 'flight_history' not in session: session['flight_history'] = []
    
    if request.method == 'POST':
        search_type = request.form.get('search_type', 'flight')
        search_query = request.form.get('search_query') or request.form.get('flight_number')
        
        if search_query:
            # Dynamically reload key in case .env was modified after server start
            flight_fetcher.api_key = os.getenv("AVIATIONSTACK_API_KEY")
            
            if search_type == 'airport':
                flight_data = flight_fetcher.fetch_flights_by_airport(search_query)
            elif search_type == 'country':
                flight_data = flight_fetcher.fetch_flights_by_country(search_query)
            else:
                flight_data = flight_fetcher.fetch_flight(search_query)
            
            # Save search history
            hist_item = f"{search_type.upper()}: {search_query.upper()}" if search_type != 'flight' else search_query.upper()
            if hist_item not in session['flight_history']:
                session['flight_history'] = [hist_item] + session['flight_history'][:4]
                session.modified = True
                
        return render_template('flight.html', data=flight_data, history_list=session['flight_history'], search_type=search_type, search_query=search_query)

    return render_template('flight.html', data=flight_data, history_list=session['flight_history'], search_type='flight', search_query='')

if __name__ == '__main__':
    app.run(debug=True)