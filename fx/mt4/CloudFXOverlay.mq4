//+------------------------------------------------------------------+
//|                                               CloudFXOverlay.mq4  |
//|  Reads the local feed file written by CloudFXFeed (the fetcher    |
//|  EA) and overlays, on the current chart:                         |
//|    1) expected-range lines (平均/±1σ/±2σ/±3σ) built from the      |
//|       broker's own live D1 open + the feed's μ/σ coefficients,   |
//|    2) a marker at the latest recorded (概算) daily close,         |
//|    3) the validated close-to-close reversal signal (≥60%),       |
//|       evaluated LIVE on the broker's own D1 closes, with arrow   |
//|       + alert when the setup is present.                         |
//|                                                                  |
//|  Attach to as many charts as you like. It does NO network I/O    |
//|  (that is CloudFXFeed's job) so it is UI-safe and coexists with  |
//|  a trading EA on the same chart.                                 |
//|                                                                  |
//|  Prices here are a statistical overlay, NOT execution prices.    |
//+------------------------------------------------------------------+
#property copyright "CloudFX"
#property link      ""
#property version   "1.00"
#property strict
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0

input string InpFileName   = "cloudfx_feed.csv"; // must match CloudFXFeed
input string InpSuffix     = "";                  // broker symbol suffix, e.g. "m" or ".pro"
input string InpGoldSymbol = "XAUUSD";            // your broker's gold symbol (before suffix)
input int    InpMaxSigma   = 2;                   // draw up to ±Nσ (0..3)
input bool   InpShowMean   = true;                // also draw the mean (k=0) expected hi/lo
input bool   InpShowClose  = true;                // draw the latest recorded close marker
input bool   InpShowSignal = true;                // evaluate + mark the reversal signal
input bool   InpAlert      = true;                // popup/sound alert when signal present
input int    InpRedrawSec  = 20;                  // reload feed + redraw interval (seconds)

const string PFX = "CFX_";

// parsed feed row for THIS chart's symbol
bool   g_has = false;
string g_fdate = "";
double g_close = 0, g_mu = 0, g_su = 0, g_md = 0, g_sd = 0;
int    g_sig = 0, g_consec = 0, g_wins_n = 0;
double g_winrate = 0;
int    g_decimals = 5;
datetime g_lastAlertDay = 0;

int OnInit()
{
   EventSetTimer(MathMax(5, InpRedrawSec));
   Refresh();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, PFX);
   Comment("");
}

void OnTimer() { Refresh(); }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[],
                const double &open[], const double &high[], const double &low[],
                const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
{
   // redraw on new ticks too (keeps range lines pinned to the live D1 open)
   DrawAll();
   return(rates_total);
}

//+------------------------------------------------------------------+
//| Map the chart symbol to a feed key (handles suffix + gold).     |
//+------------------------------------------------------------------+
string FeedKey()
{
   string s = Symbol();
   int suf = StringLen(InpSuffix);
   if(suf > 0 && StringLen(s) > suf && StringSubstr(s, StringLen(s) - suf) == InpSuffix)
      s = StringSubstr(s, 0, StringLen(s) - suf);
   if(s == InpGoldSymbol || s == "XAUUSD" || s == "GOLD") return "GOLD";
   return s;
}

//+------------------------------------------------------------------+
//| Load + parse the feed file, pick this chart's row.              |
//+------------------------------------------------------------------+
void Refresh()
{
   g_has = false;
   string key = FeedKey();

   int h = FileOpen(InpFileName, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
   {
      Comment("CloudFXOverlay\nフィード未取得: CloudFXFeed(EA)を1つのチャートに適用してください。");
      return;
   }
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      if(StringLen(line) == 0) continue;
      if(StringSubstr(line, 0, 1) == "#") continue;
      string f[];
      int n = StringSplit(line, ',', f);
      if(n < 13) continue;
      if(f[0] == "symbol") continue;          // header
      if(f[0] != key) continue;               // not this chart

      g_fdate    = f[1];
      g_close    = StringToDouble(f[2]);
      g_decimals = (int)StringToInteger(f[3]);
      g_mu       = StringToDouble(f[4]);
      g_su       = StringToDouble(f[5]);
      g_md       = StringToDouble(f[6]);
      g_sd       = StringToDouble(f[7]);
      g_sig      = (int)StringToInteger(f[9]);
      g_consec   = (int)StringToInteger(f[10]);
      g_winrate  = StringToDouble(f[11]);
      g_wins_n   = (int)StringToInteger(f[12]);
      g_has      = true;
      break;
   }
   FileClose(h);
   DrawAll();
}

//+------------------------------------------------------------------+
//| Draw everything.                                                |
//+------------------------------------------------------------------+
void DrawAll()
{
   ObjectsDeleteAll(0, PFX);
   if(!g_has)
   {
      Comment("CloudFXOverlay\nこの銘柄(", FeedKey(), ")はフィードにありません。");
      return;
   }

   double dayOpen = iOpen(Symbol(), PERIOD_D1, 0);
   if(dayOpen <= 0) dayOpen = g_close; // fallback

   int maxk = MathMax(0, MathMin(3, InpMaxSigma));

   // mean (k=0) expected hi/lo
   if(InpShowMean)
   {
      DrawLine("mean_hi", dayOpen + g_mu,       clrSilver, STYLE_DOT, 1);
      DrawLine("mean_lo", dayOpen - g_md,       clrSilver, STYLE_DOT, 1);
      DrawTag ("mean_hi_t", dayOpen + g_mu, "予想高(平均)");
      DrawTag ("mean_lo_t", dayOpen - g_md, "予想安(平均)");
   }
   // ±kσ bands
   color upCol = clrTomato, loCol = clrMediumSeaGreen;
   for(int k = 1; k <= maxk; k++)
   {
      int style = (k == 1 ? STYLE_SOLID : k == 2 ? STYLE_DASH : STYLE_DOT);
      int width = (k == 1 ? 1 : 1);
      double hi = dayOpen + g_mu + k * g_su;
      double lo = dayOpen - (g_md + k * g_sd);
      DrawLine("hi" + IntegerToString(k), hi, upCol, style, width);
      DrawLine("lo" + IntegerToString(k), lo, loCol, style, width);
      DrawTag ("hi" + IntegerToString(k) + "t", hi, "予想高 +" + IntegerToString(k) + "σ");
      DrawTag ("lo" + IntegerToString(k) + "t", lo, "予想安 -" + IntegerToString(k) + "σ");
   }

   // latest recorded (概算) close marker
   if(InpShowClose)
   {
      DrawLine("close", g_close, clrGoldenrod, STYLE_SOLID, 2);
      DrawTag ("close_t", g_close, "Cloud終値 " + g_fdate + " (" + DoubleToString(g_close, g_decimals) + ")");
   }

   // signal, evaluated LIVE on the broker's own D1 closes
   string sigTxt = "シグナル無し";
   if(InpShowSignal && g_sig != 0 && g_consec >= 2)
   {
      bool present = SignalPresent();
      sigTxt = (g_sig == 1 ? "買い候補 " : "売り候補 ")
             + IntegerToString(g_consec) + (g_sig == 1 ? "連続陰→" : "連続陽→")
             + " 勝率" + DoubleToString(g_winrate * 100.0, 1) + "% (n=" + IntegerToString(g_wins_n) + ")"
             + (present ? " 【点灯】" : " 【待機】");
      if(present)
      {
         datetime bt = iTime(Symbol(), PERIOD_D1, 0);
         double lo0 = iLow(Symbol(), PERIOD_D1, 0), hi0 = iHigh(Symbol(), PERIOD_D1, 0);
         if(g_sig == 1) DrawArrow("sig", bt, lo0, 233, clrLime);      // up arrow (buy)
         else           DrawArrow("sig", bt, hi0, 234, clrRed);       // down arrow (sell)
         MaybeAlert();
      }
   }

   Comment("CloudFXOverlay  [", FeedKey(), "]\n",
           "データ最終日: ", g_fdate, "  概算終値: ", DoubleToString(g_close, g_decimals), "\n",
           "本日始値(ブローカー): ", DoubleToString(dayOpen, g_decimals), "\n",
           sigTxt, "\n",
           "※レンジ/終値は概算統計のオーバーレイ。発注価格はMT4配信を使用。");
}

//+------------------------------------------------------------------+
//| True if the feed's setup is present on the broker's D1 closes.  |
//|   sig=+1: last `consec` daily closes each below the previous    |
//|           (consecutive down) -> buy setup                        |
//|   sig=-1: last `consec` daily closes each above the previous     |
//|           (consecutive up)   -> sell setup                       |
//| Uses CLOSED bars (index 1..consec+1) so it is stable intraday.  |
//+------------------------------------------------------------------+
bool SignalPresent()
{
   int need = g_consec + 1;
   if(iBars(Symbol(), PERIOD_D1) < need + 1) return false;
   for(int i = 1; i <= g_consec; i++)
   {
      double c0 = iClose(Symbol(), PERIOD_D1, i);
      double c1 = iClose(Symbol(), PERIOD_D1, i + 1);
      if(g_sig == 1  && !(c0 < c1)) return false; // need all down
      if(g_sig == -1 && !(c0 > c1)) return false; // need all up
   }
   return true;
}

void MaybeAlert()
{
   if(!InpAlert) return;
   datetime today = iTime(Symbol(), PERIOD_D1, 0);
   if(g_lastAlertDay == today) return;           // once per day
   g_lastAlertDay = today;
   Alert("CloudFX ", Symbol(), ": ",
         (g_sig == 1 ? "買い候補" : "売り候補"),
         " ", g_consec, (g_sig == 1 ? "連続陰線→反発" : "連続陽線→反落"),
         " 勝率", DoubleToString(g_winrate * 100.0, 1), "% n=", g_wins_n);
}

//+------------------------------------------------------------------+
//| Drawing helpers                                                 |
//+------------------------------------------------------------------+
void DrawLine(string tag, double price, color col, int style, int width)
{
   string nm = PFX + tag;
   if(ObjectFind(0, nm) < 0) ObjectCreate(0, nm, OBJ_HLINE, 0, 0, price);
   ObjectSetDouble(0, nm, OBJPROP_PRICE, price);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, col);
   ObjectSetInteger(0, nm, OBJPROP_STYLE, style);
   ObjectSetInteger(0, nm, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, nm, OBJPROP_BACK, true);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
}

void DrawTag(string tag, double price, string text)
{
   string nm = PFX + tag;
   datetime t = Time[0];
   if(ObjectFind(0, nm) < 0) ObjectCreate(0, nm, OBJ_TEXT, 0, t, price);
   ObjectSetInteger(0, nm, OBJPROP_TIME, t);
   ObjectSetDouble(0, nm, OBJPROP_PRICE, price);
   ObjectSetString(0, nm, OBJPROP_TEXT, " " + text);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, clrDimGray);
   ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, nm, OBJPROP_ANCHOR, ANCHOR_LEFT);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
}

void DrawArrow(string tag, datetime t, double price, int code, color col)
{
   string nm = PFX + tag;
   if(ObjectFind(0, nm) < 0) ObjectCreate(0, nm, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, nm, OBJPROP_TIME, t);
   ObjectSetDouble(0, nm, OBJPROP_PRICE, price);
   ObjectSetInteger(0, nm, OBJPROP_ARROWCODE, code);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, col);
   ObjectSetInteger(0, nm, OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
}
//+------------------------------------------------------------------+
