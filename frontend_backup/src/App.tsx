import type { ReactElement } from "react";
import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { NAV_ITEMS } from "./lib/nav";
import HomePage from "./pages/HomePage";
import PipelinePage from "./pages/PipelinePage";
import PlaceholderPage from "./pages/PlaceholderPage";
import ResultsPage from "./pages/ResultsPage";

const BUILT_PAGES: Readonly<Record<string, ReactElement>> = {
  "/pipeline": <PipelinePage />,
  "/results": <ResultsPage />,
};

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        {NAV_ITEMS.filter((item) => item.path !== "/").map((item) => (
          <Route
            key={item.path}
            path={item.path}
            element={
              BUILT_PAGES[item.path] ?? (
                <PlaceholderPage title={item.label} summary={item.summary} />
              )
            }
          />
        ))}
        <Route
          path="*"
          element={
            <PlaceholderPage title="Page not found" summary="Check the address or use the menu." />
          }
        />
      </Route>
    </Routes>
  );
}
