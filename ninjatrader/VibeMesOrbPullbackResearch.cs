// Research-only MES opening-range pullback strategy for NinjaTrader Strategy Analyzer.
#region Using declarations
using System;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class VibeMesOrbPullbackResearch : Strategy
    {
        private SMA dailyTrend;
        private DateTime sessionDate = DateTime.MinValue;
        private DateTime rangeEnd;
        private double openingHigh;
        private double openingLow;
        private double cumulativePriceVolume;
        private double cumulativeVolume;
        private int barsAfterRange;
        private int breakoutDirection;
        private bool openingRangeReady;
        private bool tradedToday;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Research-only one-contract MES ORB/VWAP pullback for Strategy Analyzer.";
                Name = "VibeMesOrbPullbackResearch";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                BarsRequiredToTrade = 30;
                DefaultQuantity = 1;
                IsInstantiatedOnEachOptimizationIteration = false;
                StartBehavior = StartBehavior.WaitUntilFlat;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling = StopTargetHandling.PerEntryExecution;
                TimeInForce = TimeInForce.Day;

                OpeningRangeMinutes = 30;
                BreakoutWindowBars = 1;
                MinimumBreakoutPoints = 3.0;
                PullbackToleranceTicks = 8;
                StopTicks = 40;
                RewardRisk = 2.0;
                UseDailyTrend = true;
                TrendPeriod = 20;
                SessionStart = 83000;
                LastEntryTime = 120000;
                FlattenTime = 145500;
                SlippageTicks = 1;
            }
            else if (State == State.Configure)
            {
                AddDataSeries(BarsPeriodType.Day, 1);
                Slippage = SlippageTicks;
            }
            else if (State == State.DataLoaded)
            {
                dailyTrend = SMA(Closes[1], TrendPeriod);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0 || !IsInStrategyAnalyzer)
                return;
            if (CurrentBars[0] < BarsRequiredToTrade || CurrentBars[1] < TrendPeriod)
                return;

            int now = ToTime(Time[0]);
            if (Time[0].Date != sessionDate)
                ResetSession(Time[0].Date);

            if (now >= FlattenTime)
            {
                if (Position.MarketPosition == MarketPosition.Long)
                    ExitLong("SessionExit", "LongPullback");
                else if (Position.MarketPosition == MarketPosition.Short)
                    ExitShort("SessionExit", "ShortPullback");
                return;
            }

            if (now <= SessionStart)
                return;

            cumulativePriceVolume += ((High[0] + Low[0] + Close[0]) / 3.0) * Volume[0];
            cumulativeVolume += Volume[0];

            if (Time[0] <= rangeEnd)
            {
                openingHigh = Math.Max(openingHigh, High[0]);
                openingLow = Math.Min(openingLow, Low[0]);
                return;
            }

            if (!openingRangeReady)
            {
                openingRangeReady = openingHigh > double.MinValue && openingLow < double.MaxValue;
                if (!openingRangeReady)
                    return;
            }

            if (tradedToday || Position.MarketPosition != MarketPosition.Flat || now >= LastEntryTime)
                return;

            barsAfterRange++;
            double vwap = cumulativeVolume > 0 ? cumulativePriceVolume / cumulativeVolume : Close[0];

            if (breakoutDirection == 0 && barsAfterRange <= BreakoutWindowBars)
            {
                if (Close[0] >= openingHigh + MinimumBreakoutPoints && Close[0] > vwap)
                    breakoutDirection = 1;
                else if (Close[0] <= openingLow - MinimumBreakoutPoints && Close[0] < vwap)
                    breakoutDirection = -1;
                return;
            }

            if (breakoutDirection == 0)
                return;
            if (UseDailyTrend && !TrendAllows(breakoutDirection))
                return;

            double tolerance = PullbackToleranceTicks * TickSize;
            if (breakoutDirection == 1 && Low[0] <= openingHigh + tolerance && Close[0] > openingHigh - tolerance)
            {
                SetStopLoss("LongPullback", CalculationMode.Ticks, StopTicks, false);
                SetProfitTarget("LongPullback", CalculationMode.Ticks, Math.Max(1, (int)Math.Round(StopTicks * RewardRisk)));
                EnterLong(1, "LongPullback");
                tradedToday = true;
            }
            else if (breakoutDirection == -1 && High[0] >= openingLow - tolerance && Close[0] < openingLow + tolerance)
            {
                SetStopLoss("ShortPullback", CalculationMode.Ticks, StopTicks, false);
                SetProfitTarget("ShortPullback", CalculationMode.Ticks, Math.Max(1, (int)Math.Round(StopTicks * RewardRisk)));
                EnterShort(1, "ShortPullback");
                tradedToday = true;
            }
        }

        private void ResetSession(DateTime date)
        {
            sessionDate = date;
            int hour = SessionStart / 10000;
            int minute = (SessionStart / 100) % 100;
            rangeEnd = date.AddHours(hour).AddMinutes(minute + OpeningRangeMinutes);
            openingHigh = double.MinValue;
            openingLow = double.MaxValue;
            cumulativePriceVolume = 0;
            cumulativeVolume = 0;
            barsAfterRange = 0;
            breakoutDirection = 0;
            openingRangeReady = false;
            tradedToday = false;
        }

        private bool TrendAllows(int direction)
        {
            double priorDailyClose = Closes[1][0];
            double trendValue = dailyTrend[0];
            return direction > 0 ? priorDailyClose > trendValue : priorDailyClose < trendValue;
        }

        #region Properties
        [NinjaScriptProperty]
        [Range(5, 90)]
        [Display(Name = "Opening range minutes", GroupName = "Signal", Order = 0)]
        public int OpeningRangeMinutes { get; set; }

        [NinjaScriptProperty]
        [Range(1, 10)]
        [Display(Name = "Breakout window bars", GroupName = "Signal", Order = 1)]
        public int BreakoutWindowBars { get; set; }

        [NinjaScriptProperty]
        [Range(0.25, 20.0)]
        [Display(Name = "Minimum breakout points", GroupName = "Signal", Order = 2)]
        public double MinimumBreakoutPoints { get; set; }

        [NinjaScriptProperty]
        [Range(1, 40)]
        [Display(Name = "Pullback tolerance ticks", GroupName = "Signal", Order = 3)]
        public int PullbackToleranceTicks { get; set; }

        [NinjaScriptProperty]
        [Range(4, 80)]
        [Display(Name = "Stop ticks", GroupName = "Risk", Order = 0)]
        public int StopTicks { get; set; }

        [NinjaScriptProperty]
        [Range(0.5, 4.0)]
        [Display(Name = "Reward risk", GroupName = "Risk", Order = 1)]
        public double RewardRisk { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Use daily trend", GroupName = "Filters", Order = 0)]
        public bool UseDailyTrend { get; set; }

        [NinjaScriptProperty]
        [Range(5, 100)]
        [Display(Name = "Trend period", GroupName = "Filters", Order = 1)]
        public int TrendPeriod { get; set; }

        [NinjaScriptProperty]
        [Range(0, 235959)]
        [Display(Name = "Session start (HHmmss)", GroupName = "Session", Order = 0)]
        public int SessionStart { get; set; }

        [NinjaScriptProperty]
        [Range(0, 235959)]
        [Display(Name = "Last entry (HHmmss)", GroupName = "Session", Order = 1)]
        public int LastEntryTime { get; set; }

        [NinjaScriptProperty]
        [Range(0, 235959)]
        [Display(Name = "Flatten time (HHmmss)", GroupName = "Session", Order = 2)]
        public int FlattenTime { get; set; }

        [NinjaScriptProperty]
        [Range(0, 10)]
        [Display(Name = "Slippage ticks", GroupName = "Costs", Order = 0)]
        public int SlippageTicks { get; set; }
        #endregion
    }
}

