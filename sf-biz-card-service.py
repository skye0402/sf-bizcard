import qrcode
from PIL import Image
import base64
import os
import requests
from flask import Flask, make_response, request, jsonify, g
import configparser
import sqlite3
import uuid
import datetime

app = Flask(__name__)

DATABASE = 'bizcard.db'
KYMAURL = ''

# Helper function for K8S deployment
def endless_loop(msg):
    print(msg + " Entering endless loop. Check and redo deployment?")
    while True:
        pass

# Step 1: Get assertion (base64 encoded)
def getAssertion(clientId, userId, idpUrl, tokenUrl, key) -> str:
    formBody = { "client_id": clientId, "user_id": userId, "token_url": tokenUrl, "private_key": key }
    res = requests.post(url=idpUrl, data=formBody)
    return res.content

# Step 2: Get bearer token
def getToken(clientId, companyId, grantType, tokenUrl, assertion) -> str:
    formBody = { "client_id": clientId, "grant_type": grantType, "company_id": companyId, "assertion": assertion }
    res = requests.post(url=tokenUrl, data=formBody)
    return res.content

# Create QR Code and convert to base64
def getQrCode(qrKey) -> str:
    global KYMAURL
    logo = Image.open('saplogo.png')
    # adjust image size
    basewidth = 100
    wpercent = (basewidth/float(logo.size[0]))
    hsize = int((float(logo.size[1])*float(wpercent)))
    logo = logo.resize((basewidth, hsize), Image.ANTIALIAS)
    qrCode = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H)
    qrCode.add_data(KYMAURL + '/getNameCard?onetime=' + qrKey)
    qrCode.make()
    # taking color name from user
    qrColor = 'Blue'    
    # adding color to QR code
    qrImg = qrCode.make_image(fill_color=qrColor, back_color="white").convert('RGB')    
    # set size of QR code
    pos = ((qrImg.size[0] - logo.size[0]) // 2, (qrImg.size[1] - logo.size[1]) // 2)
    qrImg.paste(logo, pos)
    # save the QR code generated
    qrImg.save(qrKey + '.png')
    qrCodeFile = open(qrKey + '.png', 'rb')
    qrCodeFileData = qrCodeFile.read()
    qrCodeFile.close()
    os.remove(qrKey + '.png')
    return base64.b64encode(qrCodeFileData).decode('ascii')

# SQLite related functions ------------------>>>
def createConnection() -> sqlite3.connect:
    return sqlite3.connect(DATABASE)

def createTable(conn):
    conn.execute('''CREATE TABLE if not exists BIZCARDREQUEST(
                ID              INTEGER PRIMARY KEY AUTOINCREMENT,
                UUID            TEXT NOT NULL,
                CREATIONTS      TIMESTAMP);''')

def createEntry(conn) -> str:
    insertQuery = "INSERT into BIZCARDREQUEST (UUID,CREATIONTS) VALUES (?, ?);"
    newUuid = str(uuid.uuid1())
    conn.execute(insertQuery, (newUuid, datetime.datetime.now()))
    conn.commit()
    return newUuid

def selectUuid(conn, key):
    foundUuid = False
    selectQuery = "SELECT * from BIZCARDREQUEST where UUID = ?;"
    cursor = conn.cursor()
    cursor.execute(selectQuery, (key,))
    records = cursor.fetchall()
    for row in records:
        print("Found with db-key ",str(row[0]),".")
        foundUuid = True
    cursor.close()
    if foundUuid:
        deleteEntry(conn,key)
    return foundUuid

def deleteEntry(conn, key) -> str:
    deleteQuery = "DELETE from BIZCARDREQUEST where UUID = ?;"
    conn.execute(deleteQuery, (key,))
    conn.commit()
    return key

def deleteOutdatedEntries(conn) -> bool:
    deleteOldQuery = "DELETE from BIZCARDREQUEST where CREATIONTS < DATETIME('now', '-1 day')"
    conn.execute(deleteOldQuery)
    conn.commit()
    return True

def getDb():
    conn = getattr(g, '_database', None)
    if conn is None:
        conn = g._database = sqlite3.connect(DATABASE)
    return conn
# SQLite related functions ------------------<<<

# Flask related functions ------------------>>>

def build_preflight_response():
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add('Access-Control-Allow-Headers', "*")
    response.headers.add('Access-Control-Allow-Methods', "*")
    return response

@app.route('/showCard', methods=['GET', 'OPTIONS'])
def showCard():
    if request.method == 'OPTIONS':
        print("Preflight response request")
        return build_preflight_response()
    else:
        print("Build QR code response")
        deleteOutdatedEntries(getDb()) #Keep the DB clean
        qrKey = createEntry(getDb())
        qrCodeBase64 = getQrCode(qrKey)
        return jsonify({ 'qrcode'      : qrKey,
                         'qrCodeImage' : qrCodeBase64 })

@app.route('/getNameCard', methods=['GET', 'OPTIONS'])   
def getNameCard():
    if request.method == 'OPTIONS':
        print("Preflight response request")
        return build_preflight_response()
    else:
        qrUuid = request.args.get('onetime')
        print("Requested namecard with UUID ", qrUuid)
        foundUuid = selectUuid(getDb(), qrUuid)
        return jsonify({ 'qrcode'      : 'Yes' })                      

@app.teardown_appcontext #Clode SQLite connection at end of program
def closeDbConnection(exception):
    conn = getattr(g, '_database', None)
    if conn is not None:
        conn.close()
        print("Closed connection to DB.")

# Flask related functions ------------------<<<

def main():
    # Read config
    config = configparser.ConfigParser(inline_comment_prefixes="#")
    config.read(['./config/sfserver.cfg'],encoding="utf8")
    if not config.has_section("server"):
        endless_loop("Config: Server section missing.")
    # -------------- Parameters ------------------>>>
    apiUrl = config.get("server","sfApiUrl")
    tokenUrl = config.get("server","sfTokenUrl")
    tokenUrl = config.get("server","sfTokenUrl")
    idpUrl = config.get("server","sfIdpUrl")
    clientId = config.get("server","clientId")
    userId = config.get("server","userId")
    grantType = config.get("server","grantType")
    companyId = config.get("server","companyId")

    flaskPort = int(config.get("flask","flaskPort"))
    flaskIp = config.get("flask","flaskIp")
    flaskDebug = config.get("flask","flaskDebug")
    flaskDebug = True if flaskDebug == 'True' else False
    global KYMAURL
    KYMAURL = config.get("kyma","kymaUrl")
    # -------------- Parameters ------------------<<<
    # Read private key
    keyFile = open('./config/privatekey.cfg', 'r')
    sfKey = keyFile.read()

    # sfAssertion = getAssertion(clientId, userId, idpUrl, tokenUrl, sfKey)
    # bearerToken = getToken(clientId, companyId, grantType, tokenUrl, sfAssertion)
    # print(bearerToken)

    # Prepare SQLite DB
    conn = createConnection()
    print("Opened QR-Code DB successfully")
    createTable(conn)
    print("Table created/checked successfully")
    conn.close()
    print("Closing connection from main")
    # print(myKey)
    # print(deleteEntry(conn,myKey))


    # Start Flask
    app.run(host=flaskIp, port=flaskPort, debug=flaskDebug)


if __name__ == '__main__':
    main()