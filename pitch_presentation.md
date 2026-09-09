@echo off
chcp 65001 >nul
title Khet2Kitchen - 3-Minute Solo Pitch & Demo Script
color 0A
cls

echo ===============================================================================
echo       🌾 KHET2KITCHEN: SOLO PITCH & LIVE DEMO WALKTHROUGH SCRIPT 🌾
echo ===============================================================================
echo  Target Duration : 2.5 - 3 Minutes
echo  Audience        : Hackathon Judges / Evaluators
echo  Presenter Role  : Solo Founder / Full-Stack & AI Lead
echo ===============================================================================
echo.
echo  Quick Links:
echo    - Farmer Portal  : http://127.0.0.1:8000/farmer/dashboard/
echo    - Produce Scan   : http://127.0.0.1:8000/farmer/graded-produce/
echo    - Pricing & MSP  : http://127.0.0.1:8000/farmer/pricing/
echo    - Wallet & UPI   : http://127.0.0.1:8000/farmer/wallet/
echo    - Consumer Shop  : http://127.0.0.1:8000/shop/
echo ===============================================================================
echo.
echo Press 1 to launch the Demo in your browser and start the spoken pitch.
echo Press 2 to read the Spoken Script stage-by-stage in this terminal.
echo.
set /p choice="Enter your choice (1 or 2): "

if "%choice%"=="1" (
    start http://127.0.0.1:8000/farmer/dashboard/
)

cls
echo ===============================================================================
echo  STAGE 1: THE HOOK & THE PROBLEM (0:00 - 0:35)
echo  [Screen: Landing Page or Farmer Dashboard]
echo ===============================================================================
echo.
echo  SPOKEN WORDS:
echo  -------------------------------------------------------------------------------
echo  "Good morning/afternoon respected judges and peers!
echo.
echo   In India today, when a farmer sells tomatoes for 10 rupees a kilo at the mandi,
echo   the urban consumer buys them for 40 rupees. Where did the remaining 30 rupees go?
echo   It was swallowed by 4 to 5 layers of middlemen, commission agents, and post-harvest
echo   spoilage. Meanwhile, farmers face arbitrary price cuts and wait weeks for money.
echo.
echo   This is KHET2KITCHEN -- India's direct farm-to-fork smart supply network that
echo   connects farmers directly to retail buyers, eliminates middlemen, guarantees MSP,
echo   and pays farmers instantly via UPI."
echo.
echo -------------------------------------------------------------------------------
pause

cls
echo ===============================================================================
echo  STAGE 2: FARMER DASHBOARD & OPTICAL AI PRODUCE SCANNER (0:35 - 1:15)
echo  [Screen: /farmer/dashboard/ -> /farmer/graded-produce/]
echo ===============================================================================
echo.
echo  SPOKEN WORDS:
echo  -------------------------------------------------------------------------------
echo  "Let's look at the Farmer Portal. We designed this completely simple so any
echo   Kisan can understand it at first glance:
echo   - 4 Big Action Cards: Scan & Sell, Today's Mandi Rates, My Wallet, and Weather.
echo.
echo   When a farmer harvests produce, they don't depend on a middleman's mood.
echo   They simply click 'Scan & Sell Crop' and take a photo.
echo.
echo   Our Edge AI Computer Vision model analyzes color uniformity, surface blemishes,
echo   and geometry against statutory AGMARK standards in seconds.
echo   It assigns a Grade A, B, or C, locks in the guaranteed MSP floor price, and
echo   generates a micro-hub drop-off slip. Zero price exploitation!"
echo.
echo -------------------------------------------------------------------------------
pause

cls
echo ===============================================================================
echo  STAGE 3: ACTION-ORIENTED VERNACULAR VOICE ASSISTANT (1:15 - 1:50)
echo  [Screen: Click the Green Floating Mic or 'Bol Kar Poochein']
echo ===============================================================================
echo.
echo  SPOKEN WORDS:
echo  -------------------------------------------------------------------------------
echo  "Most rural farmers prefer speaking in their mother tongue rather than typing.
echo   Our Vernacular Voice Assistant supports Hindi, Telugu, and English.
echo.
echo   Crucially, it is ACTION-ORIENTED. It does not just chat:
echo   - If the farmer speaks: 'मुझे टमाटर बेचने हैं' or 'Scan produce', the assistant
echo     instantly recognizes intent and triggers the camera viewfinder right on screen.
echo   - If they ask: 'क्या आज बारिश होगी?', it queries live weather telemetry for our
echo     hub in VNR VJIET and gives agronomic spraying advice."
echo.
echo -------------------------------------------------------------------------------
pause

cls
echo ===============================================================================
echo  STAGE 4: INSTANT PAYOUTS, LOGISTICS & FARM-TO-FORK TRACEABILITY (1:50 - 2:30)
echo  [Screen: /farmer/wallet/ and /farmer/logistics/]
echo ===============================================================================
echo.
echo  SPOKEN WORDS:
echo  -------------------------------------------------------------------------------
echo  "Next is money. Once produce is dropped at the local collection hub, the farmer's
echo   wallet receives the payout immediately with zero commission deductions.
echo   One click transfers the balance directly to their bank account via UPI.
echo.
echo   From the micro-hub, IoT temperature-monitored refrigerated EV vehicles transport
echo   the aggregated crates directly to urban supermarkets and consumers in under 4 hours.
echo   Buyers scan a QR code to view complete field-to-fork harvest provenance."
echo.
echo -------------------------------------------------------------------------------
pause

cls
echo ===============================================================================
echo  STAGE 5: BUSINESS IMPACT & CLOSING (2:30 - 3:00)
echo  [Screen: Return to Farmer Dashboard or Consumer Shop]
echo ===============================================================================
echo.
echo  SPOKEN WORDS:
echo  -------------------------------------------------------------------------------
echo  "In summary, Khet2Kitchen achieves three critical breakthroughs:
echo   1. Increases Farmer Income by 25 to 30 percent through 0 percent middlemen.
echo   2. Slashes Post-Harvest Food Loss to near zero using cold-chain micro-hubs.
echo   3. Delivers fresher, fully-traceable produce to consumers at fair prices.
echo.
echo   From Khet to Kitchen -- fast, fair, and transparent.
echo   Thank you! I am now happy to take your questions."
echo.
echo ===============================================================================
echo  DEMO CHEAT SHEET (COMMON JUDGE QUESTIONS):
echo  - Q: How do you handle non-produce photos?
echo    A: Edge AI produce classifier rejects non-vegetable images with a friendly alert.
echo  - Q: What if Internet is slow?
echo    A: Offline fallback caches agronomic weather and guaranteed floor prices.
echo  - Q: Who pays the logistics?
echo    A: Flat micro-hub fee of Rs 1.50/kg replaces the 12-18%% arbitrary mandi cuts.
echo ===============================================================================
echo.
echo Press any key to exit...
pause >nul
