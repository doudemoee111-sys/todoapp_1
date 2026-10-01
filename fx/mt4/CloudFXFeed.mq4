//+------------------------------------------------------------------+
//|                                                  CloudFXFeed.mq4  |
//|  Fetcher EA: downloads the CloudFX stats feed and saves it to a   |
//|  local file that the CloudFXOverlay indicator reads.             |
//|                                                                  |
//|  Attach this to ONE chart only (any symbol/timeframe). It does   |
//|  the network I/O so the indicator never has to — the indicator   |
//|  can then run on many charts and alongside your trading EA.      |
//|                                                                  |
//|  Setup (one time):                                               |
//|   Tools > Options > Expert Advisors > "Allow WebRequest for      |
//|   listed URL" and add:                                           |
//|     https://raw.githubusercontent.com                            |
//|                                                                  |
//|  NOTE: the feed carries DERIVED STATISTICS (expected-range       |
//|  coefficients + a validated signal rule), NOT tradable prices.   |
//+------------------------------------------------------------------+
#property copyright "CloudFX"
#property link      ""
#property version   "1.00"
#property strict

input string InpFeedUrl   = "https://raw.githubusercontent.com/doudemoee111-sys/todoapp_1/refs/heads/claude/cloud-business-automation-4kqckb/fx/web/mt4_feed.csv";
input string InpFileName  = "cloudfx_feed.csv"; // saved under MQL4\Files\
input int    InpRefreshMin = 60;                 // how often to re-download (minutes)
input int    InpTimeoutMs  = 5000;               // WebRequest timeout

datetime g_lastOk = 0;

int OnInit()
{
   EventSetTimer(MathMax(60, InpRefreshMin * 60));
   Fetch(); // fetch immediately on attach
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
}

void OnTimer()
{
   Fetch();
}

//+------------------------------------------------------------------+
//| Download the feed and write it to MQL4\Files\<InpFileName>.      |
//+------------------------------------------------------------------+
void Fetch()
{
   char   post[];      // empty body for GET
   char   result[];
   string result_headers;

   ResetLastError();
   int res = WebRequest("GET", InpFeedUrl, "", InpTimeoutMs, post, result, result_headers);

   if(res == -1)
   {
      int err = GetLastError();
      if(err == 4060 || err == 4014)
         Print("CloudFXFeed: WebRequest not allowed. Add https://raw.githubusercontent.com in Tools>Options>Expert Advisors.");
      else
         Print("CloudFXFeed: WebRequest failed, error ", err);
      ShowStatus("取得失敗 err=" + IntegerToString(err));
      return;
   }
   if(res != 200)
   {
      Print("CloudFXFeed: HTTP ", res);
      ShowStatus("HTTP " + IntegerToString(res));
      return;
   }

   string body = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   int h = FileOpen(InpFileName, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
   {
      Print("CloudFXFeed: cannot open ", InpFileName, " for write, error ", GetLastError());
      ShowStatus("ファイル書込失敗");
      return;
   }
   FileWriteString(h, body);
   FileClose(h);

   g_lastOk = TimeCurrent();
   ShowStatus("更新OK " + TimeToString(g_lastOk, TIME_DATE | TIME_MINUTES));
}

void ShowStatus(string msg)
{
   Comment("CloudFXFeed\n", msg, "\n保存先: MQL4\\Files\\", InpFileName);
}
//+------------------------------------------------------------------+
