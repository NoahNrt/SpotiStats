import os
import sys

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

scope = "user-read-private user-read-email"

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
    scope=scope,
    cache_path=".spotifycache",
))

### This is for getting the information of an Account
token_info = sp.auth_manager.get_access_token()
access_token = token_info["access_token"]
print(access_token)

account = sp.current_user()

print("Display name:", account.get("display_name"))
print("Spotify ID:", account.get("id"))
print("Email:", account.get("email"))
print("Country:", account.get("country"))
print("Product:", account.get("product"))
print("Account type:", account.get("type"))
print("Profile URL:", account.get("external_urls", {}).get("spotify"))
print("Followers:", account.get("followers", {}).get("total"))

'''
### This is for getting informations about an Artist.
bmth_urn = 'spotify:artist:1Ffb6ejR6Fe5IamqA5oRUF' # Always 21 Characters long
results = sp.artist_albums(bmth_urn, album_type='album', limit=10)
albums = results['items']
while results['next']:
    results = sp.next(results)
    albums.extend(results['items'])

for album in albums:
    print(album['name'])'''