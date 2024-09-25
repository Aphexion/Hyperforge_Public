#---------------------------------------------------------------------------------------
#--------------------------------------------------------------------------------------|
#                                           __                                         |
#              /\  /\_   _ _ __   ___ _ __ / _| ___  _ __ __ _  ___                    |
#             / /_/ / | | | '_ \ / _ \ '__| |_ / _ \| '__/ _` |/ _ \                   |
#            / __  /| |_| | |_) |  __/ |  |  _| (_) | | | (_| |  __/                   |
#            \/ /_/  \__, | .__/ \___|_|  |_|  \___/|_|  \__, |\___|                   |
#                    |___/|_|                            |___/                         |
#                                                                                      |
#--------------------------------------------------------------------------------------|
#--------------------------------------------------------------------------------------|
#                                                                                      |
# Hyperforge - Trading Bot Development Kit                                              |
# Hyperforge is an essential component of the SentinelALGO™ product line               |
# and operates in conjunction with the Sentrix Engines of SentinelALGO™.               |
# For more information visit www.SentinelALGO.com                                      |
#                                                                                      |
# SentinelALGO™ is a trademark of Aphexion Technologies                                |
# Aphexion Technologies - www.aphexiontech.com                                         |
# Copyright © 2023-2024 - All rights reserved.                                         |
#--------------------------------------------------------------------------------------|
#---------------------------------------------------------------------------------------


from flask import Flask, request, Response
import requests
import json
import time
import ccxt

#---------------------------------------------------------------------------------------
# EXCHANGE INITIALIZATION---------------------------------------------------------------
# The bot supports two modes: SPOT and SWAP(futures).
exchangeMode = 1 #1 for SPOT, 2 for SWAP

if exchangeMode == 1:
    exchange_id = "gateio"
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({
        'apiKey': 'YOUR SPOT APIKEY HERE',
        'secret': 'YOUR SPOT SECRET HERE',
        "options": {'defaultType': 'spot'}
        })

if exchangeMode == 2:
    exchange_id = "gateio"
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({
        'apiKey': 'YOUR FUTURES APIKEY HERE',
        'secret': 'YOUR FUTURES SECRET HERE',
        "options": {'defaultType': 'future'}
        })
#--------------------------- END OF EXCHANGE INITIALIZATION -----------------------------

#---------------------------------------------------------------------------------------
# PERIODICAL ADJUSTMENT PARAMETERS------------------------------------------------------
# Initial parameters to set the profit target and limit thresholds.
# These parameters determine the size of trades, take-profit targets, and limits.
initial_balance = 40 #Represents the total amount

takeProfitTargetPercentage = 5  # profit target
ensuredLimitThresholdPercentage = 2
#-------------------- END OF PERIODICAL ADJUSTMENT PARAMETERS --------------------------


#---------------------------------------------------------------------------------------
# OPERATIONAL MODE PARAMETERS-----------------------------------------------------------
# These parameters help to set commissions, slippage, and price proximity for orders.
spotCommision = 0.001 # spot commision for Gate.io is 0.001
slippagePercentage = 9 #This can be made adaptive based on the WinRate of the Ticker alarms. For Indicator Signals that has a Win_Rate of aboev 90% set this to 0, for signals with 55-70% set this to 20 or 30.

determineLimitPriceBasedOnOrderBook_buy = False
determineLimitPriceBasedOnOrderBook_sell = True

slippagePercentage_normalized = spotCommision * (slippagePercentage / 100)

enableStopLimit = False
stopPriceProximityPercentage_buy = spotCommision*1.75  # STOP-LIMIT ORDER Parameter, Set to 20% proximity by default, can be adjusted
stopPriceProximityPercentage_sell = spotCommision*1.75


futuresCommision_maker = 0.0002
futuresCommision_taker = 0.0005


reserved_capital_balance = initial_balance*(1 - (ensuredLimitThresholdPercentage/100)) # Reserve capital for specific position amounts, calculated based on the initial balance

numOfTickerAlarms = 1  # Number of tickers the bot is monitoring
totalPositionAmountPerAccount = 12

numOfDedicatedPositionsPerTicker = totalPositionAmountPerAccount/numOfTickerAlarms  # Number of dedicated positions per ticker

position_amount_inUSDT = reserved_capital_balance / (numOfTickerAlarms*numOfDedicatedPositionsPerTicker)  # Amount in USDT for each position

# A list to keep track of buy orders that have not been sold
unresolved_trades = []
#-------------------- END OF OPERATIONAL MODE PARAMETERS -------------------------------


#---------------------------------------------------------------------------------------
# MAIN EVENT HANDLER FOR WEBHOOK -------------------------------------------------------
# This section defines the main webhook that listens for incoming trading signals 
# and processes them accordingly.

app = Flask(__name__)

@app.route('/')
def home():
    return 'Hyperforge is ACTIVE!!!'

@app.route('/webhook', methods=['POST'])
def return_response():
    try:
        data = request.data.decode('utf-8')
        telegram_bot_sendtext(data)
        
        strArr = data.split("\n")
        order_type_arr = strArr[0].split(":")
        symbol = order_type_arr[len(order_type_arr) - 1].replace("USDT", "/USDT")
        
        entry_price_temp = strArr[5].split("=")[1]
        entry_price = entry_price_temp.split(" ")[1]

        side = order_type_arr[0].split("-")    
        side_msg = ""
        if "BUY" in side[0]:
            side_msg = "BUY"
        elif "SELL" in side[0]:
            side_msg = "SELL"
        
        #---------------------------------------
        if exchangeMode==2:
            exchange.load_markets()
            symbolFutures = symbol.strip(' ') + ':USDT'
            market_data = exchange.market(symbolFutures)
            precision = market_data['precision']['amount']
            #telegram_bot_sendtext("PRECISION: " + str(precision))  # monitor
        #---------------------------------------
                  
        currentBalanceText = getBalance()

        if "BAR CLOSE" in side[1]:
        
            queryTradesInMinutes = 35
            currentBalanceText = getBalance()
            symbol_average_price, symbol_avail_amount, symbol_total_cost = generate_trade_summary(symbol, queryTradesInMinutes, currentBalanceText)
            
            
            message_compiled = "SYMBOL:" + symbol + "," + "INDICATOR_PRICE:" + entry_price + "," + "SIDE:" + side_msg
            telegram_bot_sendtext(message_compiled)  # monitor
            
            openOrders = exchange.fetch_open_orders()
            
            optimal_bid_price, optimal_ask_price = analyze_order_book(symbol)
            
            if "BUY" in side[0]:
                manage_open_buy_orders(openOrders)
                                
                #-----------------------------------------------
                # SPOT BUY  ------------------------------------
                if exchangeMode == 1:
                    order_book = exchange.fetch_order_book(symbol)
                    order_book_price = float(order_book['bids'][0][0]) * (1-spotCommision-slippagePercentage_normalized)
                    
                    order_book_price_temp = order_book_price
                    if order_book_price_temp < optimal_bid_price:
                        order_book_price = order_book_price_temp
                    else:
                        order_book_price = optimal_bid_price
                                     
                    if determineLimitPriceBasedOnOrderBook_buy == True :
                        limit_price = order_book_price
                    else:
                        entry_price_commisioned = float(entry_price) * (1-spotCommision-slippagePercentage_normalized) 
                        limit_price = entry_price_commisioned
                        
                        
                    orderAmount = float(position_amount_inUSDT / limit_price)
                    
                   
                    if enableStopLimit == True: #This is experimental and this portion of the if statement is left here as a reference code. Do not use for normal operations.
                        # Calculate stop price based on proximity percentage to order book price
                        proximity_threshold = (stopPriceProximityPercentage_buy / 100)
                        ticker = exchange.fetch_ticker(symbol)
                        current_price = ticker['last']
                        stop_price = current_price + (current_price*proximity_threshold)
                        create_stop_limit_buy_order(symbol, orderAmount, stop_price, limit_price, True)
                    elif (limit_price <= symbol_average_price or symbol_average_price == 0):
                        exchange.create_limit_buy_order(symbol, orderAmount, limit_price)
                # -----------------------------END OF SPOT BUY     
                
         
                
                #-----------------------------------------------
                # (WORK IN PROGRESS) FUTURES LONG  --------------------------------
                elif exchangeMode == 2: # This is experimental. Use this condition for FUTURES Based Bot Implementations
                    order_book = exchange.fetch_order_book(symbol)
                    order_book_price = float(order_book['bids'][0][0]) * (1-futuresCommision_taker)
                
                    orderAmount = precision
                    exchange.create_limit_buy_order(symbolFutures, orderAmount, order_book_price)
                # ---------------------------- (WORK IN PROGRESS) END OF FUTURES LONG 
                    
                telegram_bot_sendtext("SYMBOL:" + symbol + " BUY - ORDER AMOUNT: " + str(orderAmount) + ", INDICATOR_PRICE:" + entry_price + ", ORDER PRICE: "+str(order_book_price) + ", COMMISIONED PRICE: "+str(order_book_price_temp) + ", ORDERBOOK ANALYSIS PRICE: "+str(optimal_bid_price))  # monitor
                
            elif "SELL" in side[0]:
                manage_open_sell_orders(openOrders)                
                
                #-----------------------------------------------
                # SPOT SELL  -----------------------------------
                if exchangeMode == 1:
                    order_book = exchange.fetch_order_book(symbol)
                    order_book_price = float(order_book['asks'][0][0]) * (1+spotCommision+slippagePercentage_normalized)
                    
                    order_book_price_temp = order_book_price
                    if order_book_price_temp > optimal_bid_price:
                        order_book_price = order_book_price_temp
                    else:
                        order_book_price = optimal_bid_price
                    
                    if determineLimitPriceBasedOnOrderBook_sell == True :
                        limit_price = order_book_price
                    else:
                        entry_price_commisioned = float(entry_price) * (1+spotCommision+slippagePercentage_normalized)
                        limit_price = entry_price_commisioned
                    
                                       
                    orderAmount = float(position_amount_inUSDT / limit_price)
                    
                    if enableStopLimit == True: #This is experimental and this portion of the if statement is left here as a reference code. Do not use for normal operations.
                        
                        proximity_threshold = (stopPriceProximityPercentage_sell / 100)
                        ticker = exchange.fetch_ticker(symbol)
                        current_price = ticker['last']
                        stop_price = current_price - (current_price*proximity_threshold)
                        
                        create_stop_limit_sell_order(symbol, orderAmount, stop_price, limit_price, True)
                        
                    elif (limit_price >= symbol_average_price or symbol_average_price == 0):
                    
                        symbol_average_price_commisionAdded = symbol_average_price * (1+spotCommision)
                        
                        if (limit_price >= symbol_average_price_commisionAdded):  
                            telegram_bot_sendtext("SYMBOL:" + symbol +"ASSET CLEARANCE OPPORTUNITY, Sweep Trial Initiated.")
                            exchange.create_limit_sell_order(symbol, symbol_avail_amount*0.98, limit_price)
                        else :
                            exchange.create_limit_sell_order(symbol, orderAmount, limit_price)
                                   
                # -------------------------------END OF SPOT SELL   
                
                
                
                #-----------------------------------------------
                # (WORK IN PROGRESS) FUTURES SHORT --------------------------------
                elif exchangeMode == 2: # This is experimental. Use this condition for FUTURES Based Bot Implementations
                    order_book = exchange.fetch_order_book(symbol)
                    order_book_price = float(order_book['asks'][0][0]) * (1+futuresCommision_maker)
                
                    orderAmount = precision
                    exchange.create_limit_sell_order(symbolFutures, orderAmount, order_book_price)
                # --------------------------- (WORK IN PROGRESS) END OF FUTURES SHORT 
                             
                telegram_bot_sendtext("SYMBOL:" + symbol +" SELL - ORDER AMOUNT: " + str(orderAmount) + ", INDICATOR_PRICE:" + entry_price + ", ORDER PRICE: "+str(order_book_price) + ", COMMISIONED PRICE: "+str(order_book_price_temp) + ", ORDERBOOK ANALYSIS PRICE: "+str(optimal_bid_price))  # monitor
                

        total_balance, usdt_balance, asset_balances, locked_balances, total_asset_balances_in_usdt, position_amounts = calculate_total_balance(currentBalanceText, position_amount_inUSDT)
        telegram_bot_sendtext("Total Balance in USDT:"+str(total_balance))  # monitor
        telegram_bot_sendtext("Position Amounts:"+str(position_amounts)+" ,Position Size in USDT:"+str(position_amount_inUSDT)+" ,Capital in USDT:"+str(initial_balance) +", Reserved Capital in USDT:"+str(reserved_capital_balance))  # monitor 
        
        take_profit_if_target_reached(total_balance, initial_balance, asset_balances, locked_balances,takeProfitTargetPercentage) # Check if profit target is reached and take action


        
    except Exception as e:
        telegram_bot_sendtext(str(e))
        telegram_bot_sendtext("EXCEPTION STATE - CURRENT BALANCE REPORT:" + getBalance())
        print(str(e))

    return Response(status=200)
#-------------------- END OF MAIN EVENT HANDLER FOR WEBHOOK ----------------------------

# Hyperforge API
#---------------------------------------------------------------------------------------
# LIBRARY FUNCTIONS: BALANCE FETCHING --------------------------------------------------

# This function fetches the current balance from the Gate.io exchange
# and returns the balance information in text format.
def getBalance():
    balance = exchange.fetch_balance()

    balance_text = "BALANCE:"
    for info in balance['info']:
        balance_text = balance_text + str(info)

    print(balance_text)
    return balance_text
#-------------------- END OF LIBRARY FUNCTIONS: BALANCE FETCHING -----------------------

#---------------------------------------------------------------------------------------
# LIBRARY FUNCTIONS: STOP LIMIT ORDERS -------------------------------------------------

# Function to create stop-limit buy order, handling fallback in case of failure.
def create_stop_limit_buy_order(symbol, amount, stop_buy_price, limit_buy_price, enableInsteadMode):
    params = {
        'triggerPrice': stop_buy_price,
    }
    try:      
        order=exchange.create_limit_buy_order(symbol, amount, limit_buy_price, params)
        telegram_bot_sendtext(f"Placed a buy stop-limit order for {amount} {symbol} with stop price {stop_buy_price} and limit price {limit_buy_price}.")
        print(order)
    except Exception as e:
        if enableInsteadMode == true :
            telegram_bot_sendtext(f"Failed to place buy stop-limit order for {amount} {symbol}: {e}, Generating Normal Limit Buy Order instead.")
            print(f"Failed to place order: {e}, Generating Normal Limit Buy Order instead.")
            exchange.create_limit_buy_order(symbol, amount, limit_buy_price)
        else :
            telegram_bot_sendtext(f"Failed to place buy stop-limit order for {amount} {symbol}: {e}")
            print(f"Failed to place order: {e}")
            exchange.create_limit_buy_order(symbol, amount, limit_buy_price)

# Function to create stop-limit sell order, handling fallback in case of failure.
def create_stop_limit_sell_order(symbol, amount, stop_sell_price, limit_sell_price, enableInsteadMode):
    params = {
        'triggerPrice': stop_sell_price,
    }
    try:      
        order=exchange.create_limit_sell_order(symbol, amount, limit_sell_price, params)
        telegram_bot_sendtext(f"Placed a sell stop-limit order for {amount} {symbol} with stop price {stop_sell_price} and limit price {limit_sell_price}.")
        print(order)
    except Exception as e:
        if enableInsteadMode == true :
            telegram_bot_sendtext(f"Failed to place sell stop-limit order for {amount} {symbol}: {e}, Generating Normal Limit Sell Order instead.")
            exchange.create_limit_sell_order(symbol, amount, limit_sell_price)
            print(f"Failed to place order: {e}, Generating Normal Limit Sell Order instead.")
        else :
            telegram_bot_sendtext(f"Failed to place sell stop-limit order for {amount} {symbol}: {e}")
            print(f"Failed to place order: {e}")
#-------------------- END OF LIBRARY FUNCTIONS: STOP LIMIT ORDERS ----------------------

#---------------------------------------------------------------------------------------
# LIBRARY FUNCTIONS: ORDER MANAGEMENT --------------------------------------------------

# Function to manage open buy orders. It checks if there are too many buy orders,
# and cancels the lowest-priced obsolete orders.
def manage_open_buy_orders(open_orders):
    try:
        buy_orders = [order for order in open_orders if order['side'] == 'buy']

        if len(buy_orders) >= 3:
            lowest_buy_order = min(buy_orders, key=lambda x: float(x['price']))
            symbol = lowest_buy_order['symbol']  # Extract the symbol from the order
            telegram_bot_sendtext("OBSOLETE BUY ORDER CANCEL")
            cancel_order(lowest_buy_order['id'], symbol)

            # Track unresolved trades
            for order in buy_orders:
                if order['status'] == 'closed':
                    unresolved_trades.append(order)

        # Check and handle any unresolved trades # This Function
        check_for_slippage()

    except Exception as e:
        infoText = f"An error occurred while managing open buy orders: {e}"
        telegram_bot_sendtext(infoText)
        print(infoText)

# Function to manage open sell orders. It checks if there are too many sell orders,
# and cancels the highest-priced obsolete orders.
def manage_open_sell_orders(open_orders):
    try:
        sell_orders = [order for order in open_orders if order['side'] == 'sell']

        if len(sell_orders) >= 3:
            highest_sell_order = max(sell_orders, key=lambda x: float(x['price']))
            symbol = highest_sell_order['symbol']  # Extract the symbol from the order
            telegram_bot_sendtext("OBSOLETE SELL ORDER CANCEL")
            cancel_order(highest_sell_order['id'], symbol)


            # Track unresolved trades
            for order in sell_orders:
                if order['status'] == 'closed':
                    unresolved_trades.append(order)

        # Check and handle any unresolved trades
        check_for_slippage()

    except Exception as e:
        infoText = f"An error occurred while managing open sell orders: {e}"
        telegram_bot_sendtext(infoText)
        print(infoText)

# Function to cancel a specific order by its ID
def cancel_order(order_id, symbol):
    try:
        exchange.cancel_order(order_id, symbol)
        infoText = f"Order {order_id} canceled successfully for market {symbol}."
        telegram_bot_sendtext(infoText)
        print(infoText)
    except Exception as e:
        infoText = f"Failed to cancel order {order_id}: {e}"
        telegram_bot_sendtext(infoText)
        print(infoText)  
#-------------------- END OF LIBRARY FUNCTIONS: ORDER MANAGEMENT -----------------------

#---------------------------------------------------------------------------------------
# (DISCLAIMER:WORK IN PROGRESS) SLIPPAGE ADAPTIVE PROTECTION MECHANISM -----------------

# The slippage protection mechanism checks unresolved trades and applies adaptive
# strategies based on time elapsed and price movements.
def check_for_slippage():
    for trade in unresolved_trades:
        adaptive_protection(trade)

# Applies slippage protection logic to specific trades
def adaptive_protection(trade):
    try:
        current_price = float(exchange.fetch_ticker(trade['symbol'])['last'])
        purchase_price = float(trade['price'])
        time_elapsed = (time.time() - (trade['timestamp'] / 1000)) / 60  # in minutes

        # Adaptive strategies based on time elapsed
        if time_elapsed > 10:
            telegram_bot_sendtext(f"Trade {trade['id']} has been unresolved for over 1 hour. Selling at market price.")
            place_market_sell_order(trade['symbol'], trade['amount'])
            unresolved_trades.remove(trade)
        
        # Adaptive strategies based on price movement
        price_threshold = 0.98  # Example: 2% drop from purchase price
        if current_price < purchase_price * price_threshold:
            telegram_bot_sendtext(f"Trade {trade['id']} is at a loss beyond 2%. Selling at market price.")
            place_market_sell_order(trade['symbol'], trade['amount'])
            unresolved_trades.remove(trade)

    except Exception as e:
        infoText = f"An error occurred during adaptive protection: {e}"
        telegram_bot_sendtext(infoText)
        print(infoText)

# Function to place a market sell order for an asset (WORK IN PROGRESS since GateIO only supports limit orders)
def place_market_sell_order(symbol, amount):
    try:
        sell_order = exchange.create_market_sell_order(symbol, amount)
        telegram_bot_sendtext(f"Market sell order placed: {sell_order}")
        print(f"Market sell order placed: {sell_order}")
    except Exception as e:
        telegram_bot_sendtext(f"Failed to place market sell order: {e}")
        print(f"Failed to place market sell order: {e}")
#-------------------- #END OF (WORK IN PROGRESS) SLIPPAGE ADAPTIVE PROTECTION MECHANISM

#---------------------------------------------------------------------------------------
# LIBRARY FUNCTIONS: ORDERBOOK ANALYSIS ------------------------------------------------

# Function to analyze the order book of a given symbol and find optimal bid and ask prices.
# This is useful for deciding the best price to place limit orders.
def analyze_order_book(symbol):
    volume_threshold = 10 # Developer tip: This can be made adaptive.
    
    order_book = exchange.fetch_order_book(symbol)
    bids = order_book['bids']  # List of [price, volume]
    asks = order_book['asks']  # List of [price, volume]
    
    # Calculate cumulative volume for bids
    cumulative_bid_volume = 0
    optimal_bid_price = None
    
    for bid in bids:
        price, volume = bid
        cumulative_bid_volume += volume
        if cumulative_bid_volume >= volume_threshold:
            optimal_bid_price = price
            break

    # Calculate cumulative volume for asks
    cumulative_ask_volume = 0
    optimal_ask_price = None
    
    for ask in asks:
        price, volume = ask
        cumulative_ask_volume += volume
        if cumulative_ask_volume >= volume_threshold:
            optimal_ask_price = price
            break

    return optimal_bid_price, optimal_ask_price
#-------------------- END OF LIBRARY FUNCTIONS: ORDERBOOK ANALYSIS ---------------------

#---------------------------------------------------------------------------------------
# (DISCLAIMER:WORK IN PROGRESS) TAKE TARGET PROFIT -------------------------------------
# This section is marked as WORK IN PROGRESS because it is being adapted for Gate.io's
# lack of direct support for market orders, and thus requires recursive limit sell orders.

# Function to fetch asset prices and calculate the total balance for the account.
def get_asset_prices(assets):
    prices = {}
    for asset in assets:
        if asset != 'USDT':
            symbol = f"{asset}/USDT"
            try:
                ticker = exchange.fetch_ticker(symbol)
                prices[asset] = ticker['last']
                #print(f"Fetched price for {symbol}: {ticker['last']}") #debug
            except Exception as e:
                prices[asset] = 0  # Set to 0 if unable to fetch the price
                print(f"Failed to fetch price for {symbol}: {e}")
    return prices

# Function to calculate the total balance in USDT based on current asset holdings.
def calculate_total_balance(balance_text, position_amount_inUSDT):
    # print("Raw Balance Text:", balance_text)#debug

    # Ensure the balance text is properly formatted
    balance_text = balance_text.replace("BALANCE:", "")
    balance_text = balance_text.replace("}{", "}~{")  # Use ~ as a separator for easier splitting
    balance_text = balance_text.replace("'", "\"")  # Replace single quotes with double quotes for JSON parsing

    # Split into individual balance entries
    balances = balance_text.split("~")

    total_balance = 0
    usdt_balance = 0
    asset_balances = {}
    locked_balances = {}
    total_asset_balances_in_usdt = {}
    position_amounts = {}

    for balance in balances:
        try:
            balance_info = json.loads(f"{balance}")
            currency = balance_info['currency']
            available = float(balance_info['available'])
            locked = float(balance_info['locked'])

            # Total of available and locked balances
            total_currency_balance = available + locked

            if currency != 'USDT':
                asset_balances[currency] = total_currency_balance
                locked_balances[currency] = locked
            else:
                usdt_balance = total_currency_balance
                total_balance += usdt_balance
                locked_balances[currency] = locked

            #print(f"Currency: {currency}, Available: {available}, Locked: {locked}, Total: {total_currency_balance}") #debug

        except Exception as e:
            print(f"Error parsing balance entry: {balance}")
            print(f"Exception: {e}")

    # Fetch current prices and calculate total balance in USDT
    prices = get_asset_prices(asset_balances.keys())
    for asset, total_currency_balance in asset_balances.items():
        price = prices.get(asset, 0)
        if price > 0:
            converted_value = total_currency_balance * price
            total_balance += converted_value
            total_asset_balances_in_usdt[asset] = converted_value

            # Calculate the position amount
            position_amount = converted_value / position_amount_inUSDT
            position_amounts[asset] = round(position_amount)

            #print(f"Asset: {asset}, Total Balance: {total_currency_balance}, Price: {price}, Converted to USDT: {converted_value}, Position Amount: {position_amount}") #debug
        else:
            print(f"Asset: {asset}, Total Balance: {total_currency_balance}, Price: Not available or 0")

    return total_balance, usdt_balance, asset_balances, locked_balances, total_asset_balances_in_usdt, position_amounts
# The main function that takes profit when the target balance is reached.
# Since Gate.io does not support market orders, it uses recursive limit orders to
# sell assets at the best possible price
def take_profit_if_target_reached(total_balance, initial_balance, asset_balances, locked_balances, takeProfitTargetPercentage):
    target_balance = initial_balance * (1 + takeProfitTargetPercentage / 100)

    if total_balance >= target_balance:
        telegram_bot_sendtext(f"Target balance reached: {total_balance} USDT. Taking profits...")

        # Cancel all open orders
        try:
            exchange.cancel_all_orders()
            telegram_bot_sendtext("All open orders being canceled.")
            time.sleep(200)  # Wait a moment for the cancellations to process
        except Exception as e:
            telegram_bot_sendtext(f"Failed to cancel open orders: {e}")
            return  # If orders can't be canceled, stop the process

        # Attempt to sell all available and locked assets at the best possible price
        for asset, amount in asset_balances.items():
            total_amount = amount + locked_balances.get(asset, 0)  # Include locked balances
            if total_amount > 0:
                symbol = f"{asset}/USDT"
                attempts = 0
                success = False
                
                while attempts < 3 and not success:  # Try up to 3 times
                    try:
                        # Fetch the order book for the symbol
                        order_book = exchange.fetch_order_book(symbol)
                        # Use the best bid price to place a limit sell order
                        best_bid_price = order_book['bids'][0][0]

                        # Place the limit sell order at the best bid price
                        order = exchange.create_limit_sell_order(symbol, total_amount, best_bid_price)
                        
                        # Wait and check if the order was filled
                        time.sleep(200)
                        order_info = exchange.fetch_order(order['id'], symbol)
                        
                        if order_info['status'] == 'closed':
                            success = True
                            telegram_bot_sendtext(f"Successfully sold {total_amount} of {asset} at the best bid price of {best_bid_price}.")
                        else:
                            telegram_bot_sendtext(f"Order for {total_amount} of {asset} not fully executed. Retrying...")
                            exchange.cancel_order(order['id'], symbol)
                            attempts += 1

                    except Exception as e:
                        telegram_bot_sendtext(f"Failed to sell {total_amount} of {asset}: {e}")
                        attempts += 1

                if not success:
                    telegram_bot_sendtext(f"Failed to sell {total_amount} of {asset} after multiple attempts. Consider manual intervention.")

        telegram_bot_sendtext(f"Profit taken successfully. New balance: {total_balance} USDT")
    else:
        telegram_bot_sendtext(f"Current total balance: {total_balance} USDT. Profit target {target_balance} USDT not yet reached. Target Takeprofit percentage is {takeProfitTargetPercentage}%")
#-------------------- END OF (WORK IN PROGRESS) TAKE TARGET PROFIT ---------------------

#---------------------------------------------------------------------------------------
# LIBRARY FUNCTIONS: AVG ASSET PAST PRICE CALCULATOR -----------------------------------
# These functions calculate the average price of trades in the past and fetch available amounts.

# Generate a trade summary with average price, available amount, and total cost.
def generate_trade_summary(symbol, queryTradesInMinutes, currentBalanceText):
    try:
        # Get the average price of trades for the given symbol and time duration
        averagePrice = get_average_price_of_trades(symbol, queryTradesInMinutes)

        # Get the available amount for the given symbol from the current balance text
        availAmount = get_available_amount(symbol, currentBalanceText)

        # Check if the average price and available amount were successfully retrieved
        if averagePrice is not None and availAmount is not None:
            # Calculate the total cost
            total_cost = averagePrice * availAmount

            # Prepare the message to send via Telegram
            telegram_message = (
                f"{symbol} TRADE HISTORY QUERY DURATION (Mins): {queryTradesInMinutes}\n"
                f"AVG COST of ASSETS: {averagePrice:.7f}\n"
                f"AVAIL AMOUNT: {availAmount:.7f}\n"
                f"TOTAL COST: {total_cost:.7f}"
            )

            # Send the message via Telegram
            telegram_bot_sendtext(telegram_message)

            # Print the message for debugging or logging purposes
            print(telegram_message)
            return averagePrice, availAmount, total_cost
        else:
            # Handle the case where no trades or available amounts were found
            error_message = f"Failed to retrieve trade data or balance for {symbol}. Returning 0 as avg cost."
            telegram_bot_sendtext(error_message)
            print(error_message)
            return 0,0,0

    except Exception as e:
        # Handle any exceptions that occur
        error_message = f"An error occurred while generating trade summary for {symbol}: {str(e)}"
        telegram_bot_sendtext(error_message)
        print(error_message)

# Fetch the available amount of a given symbol based on the current balance text.
def get_available_amount(symbol, currentBalanceText):
    try:
        # Remove the "BALANCE:" prefix if it exists
        if currentBalanceText.startswith("BALANCE:"):
            currentBalanceText = currentBalanceText.replace("BALANCE:", "", 1)

        # Initialize a dictionary to hold the available balances
        balance_data = {}

        # Clean up the input string and split it into individual currency data strings
        currency_entries = currentBalanceText.replace("}{", "}|||{").split("|||")

        for entry in currency_entries:
            try:
                # Strip the curly braces and split the entry into key-value pairs
                entry = entry.strip('{}')
                key_value_pairs = entry.split(", ")

                # Initialize a dictionary to hold this currency's data
                currency_data = {}
                for pair in key_value_pairs:
                    key, value = pair.split(": ")
                    key = key.strip("'")  # Remove surrounding quotes from the key
                    value = value.strip("'")  # Remove surrounding quotes from the value
                    currency_data[key] = value

                # Check if 'currency' exists in currency_data
                if 'currency' in currency_data:
                    currency = currency_data['currency']
                    available = float(currency_data.get('available', 0.0))
                    # Store the available amount in the dictionary
                    balance_data[currency] = available
                else:
                    error_message = f"Skipping entry, 'currency' key not found: {currency_data}"
                    telegram_bot_sendtext(error_message)
                    print(error_message)

            except Exception as e:
                error_message = f"Error parsing balance data: {e}"
                telegram_bot_sendtext(error_message)
                print(error_message)
                continue

        # Get the base currency of the symbol
        symbol_currency = symbol.split("/")[0]  # For example, "SUN" in "SUN/USDT"

        # Return the available amount for the base currency
        return balance_data.get(symbol_currency, 0.0)

    except Exception as e:
        error_message = f"An error occurred while getting available amount for {symbol}: {str(e)}"
        telegram_bot_sendtext(error_message)
        print(error_message)
        return 0.0  # Return 0 if there is an error

# Calculate the average price of trades for a given symbol within a time window in minutes.
def get_average_price_of_trades(symbol, minutes):
    try:
        # Get the current time in milliseconds
        now = exchange.milliseconds()

        # Calculate the timestamp for `minutes` ago
        n_minutes_ago = now - (minutes * 60 * 1000)

        # Fetch trades from the last `minutes`
        trades = exchange.fetchMyTrades(symbol, since=n_minutes_ago)

        if not trades:
            message = f"No trades found in the last {minutes} minutes for {symbol}."
            telegram_bot_sendtext(message)
            print(message)
            return None

        # Calculate the weighted average price
        total_amount = 0
        weighted_sum = 0
        for trade in trades:
            trade_amount = trade['amount']
            trade_price = trade['price']
            weighted_sum += trade_amount * trade_price
            total_amount += trade_amount

        if total_amount == 0:
            message = f"No trades with non-zero amounts found for {symbol}."
            telegram_bot_sendtext(message)
            print(message)
            return None

        average_price = weighted_sum / total_amount
        #message = f"Average price of {symbol} in the last {minutes} minutes: {average_price:.4f}"
        #telegram_bot_sendtext(message)
        #print(message)
        return average_price

    except Exception as e:
        error_message = f"An error occurred while getting average price for {symbol}: {str(e)}"
        telegram_bot_sendtext(error_message)
        print(error_message)
        return None  # Return None if there is an error
#-------------------- END OF LIBRARY FUNCTIONS: AVG ASSET PAST PRICE CALCULATOR ---------

#---------------------------------------------------------------------------------------
# TELEGRAM BOT SEND FUNCTION -----------------------------------------------------------
# Function to send messages to the Telegram bot.
def telegram_bot_sendtext(bot_message):
    bot_token = 'YOUR TELEGRAM BOT TOKEN HERE'
    bot_chatID = 'YOUR TELEGRAM CHAT ID HERE'
    send_text = 'https://api.telegram.org/bot' + bot_token + '/sendMessage?chat_id=' + bot_chatID + '&text=' + bot_message

    response = requests.get(send_text)
    return response.json()
#-------------------- END OF TELEGRAM BOT SEND FUNCTION ---------------------------------

#---------------------------------------------------------------------------------------
# MAIN PROGRAM ENTRY POINT -------------------------------------------------------------
if __name__ == "__main__": 
    app.run()
    
#-------------------- END OF MAIN PROGRAM ----------------------------------------------
    