import { Suspense, lazy, type ComponentType } from "react";
import { createBrowserRouter } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";

const Home = lazy(() => import("@/pages/Home").then((m) => ({ default: m.Home })));
const TradingCockpit = lazy(() =>
  import("@/pages/TradingCockpit").then((m) => ({ default: m.TradingCockpit })),
);
const Agent = lazy(() => import("@/pages/Agent").then((m) => ({ default: m.Agent })));
const RunDetail = lazy(() =>
  import("@/pages/RunDetail").then((m) => ({ default: m.RunDetail })),
);
const Compare = lazy(() =>
  import("@/pages/Compare").then((m) => ({ default: m.Compare })),
);
const Settings = lazy(() =>
  import("@/pages/Settings").then((m) => ({ default: m.Settings })),
);
const Correlation = lazy(() =>
  import("@/pages/Correlation").then((m) => ({ default: m.Correlation })),
);
const AlphaZoo = lazy(() =>
  import("@/pages/AlphaZoo").then((m) => ({ default: m.AlphaZoo })),
);
const Watchlist = lazy(() =>
  import("@/pages/Watchlist").then((m) => ({ default: m.Watchlist })),
);
const Retro = lazy(() =>
  import("@/pages/Retro").then((m) => ({ default: m.Retro })),
);
const Journal = lazy(() =>
  import("@/pages/Journal").then((m) => ({ default: m.Journal })),
);
const Detection = lazy(() =>
  import("@/pages/Detection").then((m) => ({ default: m.Detection })),
);
const Calibration = lazy(() =>
  import("@/pages/Calibration").then((m) => ({ default: m.Calibration })),
);

function PageLoader() {
  return (
    <div className="flex h-[60vh] items-center justify-center text-muted-foreground">
      Loading…
    </div>
  );
}

function wrap(Component: ComponentType) {
  return (
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: wrap(TradingCockpit) },
      { path: "/research", element: wrap(Home) },
      { path: "/watchlist", element: wrap(Watchlist) },
      { path: "/retro", element: wrap(Retro) },
      { path: "/journal", element: wrap(Journal) },
      { path: "/detection", element: wrap(Detection) },
      { path: "/calibration", element: wrap(Calibration) },
      { path: "/agent", element: wrap(Agent) },
      { path: "/settings", element: wrap(Settings) },
      { path: "/runs/:runId", element: wrap(RunDetail) },
      { path: "/compare", element: wrap(Compare) },
      { path: "/correlation", element: wrap(Correlation) },
      { path: "/alpha-zoo", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/bench", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/:alphaId", element: wrap(AlphaZoo) },
    ],
  },
]);
