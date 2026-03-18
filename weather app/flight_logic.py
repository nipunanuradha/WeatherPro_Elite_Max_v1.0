import os
import json
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

COUNTRY_AIRLINES = {
    'sri lanka': ['UL'],
    'usa': ['AA', 'DL', 'UA', 'WN'],
    'united states': ['AA', 'DL', 'UA', 'WN'],
    'uk': ['BA', 'VS', 'U2'],
    'united kingdom': ['BA', 'VS', 'U2'],
    'india': ['AI', '6E', 'UK'],
    'australia': ['QF', 'VA', 'JQ'],
    'canada': ['AC', 'WS'],
    'germany': ['LH'],
    'france': ['AF'],
    'uae': ['EK', 'EY'],
    'united arab emirates': ['EK', 'EY'],
    'japan': ['JL', 'NH'],
    'singapore': ['SQ'],
    'malaysia': ['MH'],
    'china': ['CA', 'CZ', 'MU'],
    'qatar': ['QR'],
    'new zealand': ['NZ']
}

class FlightFetcher:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("AVIATIONSTACK_API_KEY")
        self.base_url = "http://api.aviationstack.com/v1/flights"
        self._airports_data = None
        
    def _get_airports_data(self):
        if self._airports_data:
            return self._airports_data
            
        cache_path = os.path.join(os.path.dirname(__file__), 'airports.json')
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                self._airports_data = json.load(f)
            return self._airports_data
            
        try:
            print("Downloading airports data...")
            resp = requests.get("https://raw.githubusercontent.com/mwgg/Airports/master/airports.json", timeout=15)
            if resp.status_code == 200:
                self._airports_data = resp.json()
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(self._airports_data, f)
                return self._airports_data
        except Exception as e:
            print(f"Error fetching airports data: {e}")
            
        return {}

    def fetch_flight(self, flight_number):
        if not flight_number or not str(flight_number).strip():
            return None
        if not self.api_key:
            print("WARNING: No AviationStack API key found.")
            return None

        params = {
            'access_key': self.api_key,
            'flight_iata': flight_number.upper().strip()
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            if response.status_code != 200:
                print(f"Error: {response.status_code} - {response.text}")
                return None
            
            data = response.json()
            if 'data' in data and len(data['data']) > 0:
                flights = data['data']
                flights.sort(key=lambda x: x['departure'].get('estimated') or x['departure'].get('scheduled') or "1970", reverse=True)
                active_flight = next((f for f in flights if f['flight_status'] in ['active', 'scheduled']), None)
                return active_flight if active_flight else flights[0]
            else:
                return None
        except requests.RequestException as e:
            print(f"Request exception: {e}")
            return None

    def fetch_flights_by_airport(self, query):
        if not query or not self.api_key:
            return None
            
        original_query = str(query).strip()
        query = original_query.lower()
        
        # Check specific common aliases
        aliases = {"bia": "CMB", "colombo": "CMB"}
        target_iata = aliases.get(query)
        
        # Load airports data
        airports = self._get_airports_data()
        
        # 1. Collect all potential matches and score them
        matches = []
        for key, ap in airports.items():
            name = ap.get('name', '').lower()
            city = ap.get('city', '').lower()
            iata = ap.get('iata', '').lower()
            
            score = 0
            if target_iata and iata == target_iata.lower(): 
                score += 100
            elif query == iata: 
                score += 95
            
            if query == name: 
                score += 90
            elif query in name: 
                score += 50
            
            if query == city: 
                score += 80
            elif query in city: 
                score += 40
            
            if score > 0:
                # Strongly prioritize entries with valid 3-letter IATA codes
                if iata and len(iata) == 3 and iata != '\\N':
                    score += 200 # Heavy weight for major airports
                matches.append((ap, score))
        
        # 2. Sort matches by score descending and pick the best one
        found_ap = None
        if matches:
            matches.sort(key=lambda x: x[1], reverse=True)
            found_ap = matches[0][0]
            
        # Determine the final IATA code to use for the API
        final_iata = None
        if found_ap:
            final_iata = found_ap.get('iata')
        elif target_iata:
            final_iata = target_iata
        elif len(query) == 3:
            final_iata = query.upper()
            
        if not final_iata or final_iata == '\\N' or len(str(final_iata)) != 3:
            return None
            
        flights = []
        try:
            # Fetch Departures
            dep_params = {'access_key': self.api_key, 'dep_iata': final_iata, 'limit': 25}
            r_dep = requests.get(self.base_url, params=dep_params, timeout=10)
            if r_dep.status_code == 200:
                dep_data = r_dep.json()
                if 'data' in dep_data:
                    flights.extend(dep_data['data'])
                
            # Fetch Arrivals
            arr_params = {'access_key': self.api_key, 'arr_iata': final_iata, 'limit': 25}
            r_arr = requests.get(self.base_url, params=arr_params, timeout=10)
            if r_arr.status_code == 200:
                arr_data = r_arr.json()
                if 'data' in arr_data:
                    flights.extend(arr_data['data'])
            
            if not flights:
                print(f"DEBUG: No flights returned for IATA '{final_iata}'")
                return None # Or return a specific empty state
                
            # Filter active/scheduled/landed and sort
            valid_flights = [f for f in flights if f.get('flight_status') in ['active', 'scheduled', 'landed']]
            
            # Sort by scheduled time descending (most recent first)
            valid_flights.sort(key=lambda x: (x.get('departure', {}).get('estimated') or x.get('departure', {}).get('scheduled') or "1970"), reverse=True)

            # Remove duplicates based on flight iata + airline
            seen = set()
            unique_flights = []
            for f in valid_flights:
                flight = f.get('flight', {})
                flight_iata = flight.get('iata')
                airline_iata = f.get('airline', {}).get('iata', '')
                f_status = f.get('flight_status', '')
                
                # Use flight_iata + status to allow same flight different states if returned (unlikely)
                key = f"{flight_iata}-{airline_iata}-{f_status}"
                if flight_iata:
                    if key not in seen:
                        seen.add(key)
                        unique_flights.append(f)
                else:
                    key = f"{airline_iata}{flight.get('number')}-{f_status}"
                    if key not in seen:
                        seen.add(key)
                        unique_flights.append(f)
                        
            return {'type': 'airport', 'code': final_iata, 'flights': unique_flights}
            
        except requests.RequestException as e:
            print(f"Request exception: {e}")
            return None
            
        except requests.RequestException as e:
            print(f"Request exception: {e}")
            return None

    def fetch_flights_by_country(self, country):
        if not country or not self.api_key:
            return None
            
        country_key = str(country).strip().lower()
        airlines = COUNTRY_AIRLINES.get(country_key)
        
        if not airlines:
            # Try to partial match
            for k, v in COUNTRY_AIRLINES.items():
                if country_key in k or k in country_key:
                    airlines = v
                    break
                    
        if not airlines:
            return None
            
        flights = []
        try:
            for airline in airlines:
                params = {'access_key': self.api_key, 'airline_iata': airline, 'limit': 15}
                response = requests.get(self.base_url, params=params, timeout=10)
                if response.status_code == 200 and 'data' in response.json():
                    flights.extend(response.json()['data'])
            
            # Filter active/scheduled
            valid_flights = [f for f in flights if f.get('flight_status') in ['active', 'scheduled']]
            return {'type': 'country', 'country': country_key.title(), 'flights': valid_flights}
        except requests.RequestException as e:
            print(f"Request exception: {e}")
            return None
