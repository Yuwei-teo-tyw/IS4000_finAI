import { createBrowserRouter, Navigate } from "react-router-dom";
import LegacyIcRedirect from "./LegacyIcRedirect";
import AppShell from "../layouts/AppShell";
import { ChatContainer } from "../components/Chat/ChatContainer";
import ClientBook from "../pages/rm/ClientBook";
import RmAssistant from "../pages/rm/RmAssistant";
import PmAssistant from "../pages/pm/PmAssistant";
import OnboardingNotes from "../pages/rm/OnboardingNotes";
import OnboardingSummary from "../pages/rm/OnboardingSummary";
import IpsDraft from "../pages/rm/IpsDraft";
import IpsApproval from "../pages/rm/IpsApproval";
import QuarterlyReviewStart from "../pages/rm/QuarterlyReviewStart";
import PackReview from "../pages/rm/PackReview";
import PmInbox from "../pages/pm/PmInbox";
import ThreeLBuilder from "../pages/pm/ThreeLBuilder";
import SaaBuilder from "../pages/pm/SaaBuilder";
import SaaWeights from "../pages/pm/SaaWeights";
import SaaReview from "../pages/pm/SaaReview";
import ProductRecommendations from "../pages/pm/ProductRecommendations";
import PmMarketHealth from "../pages/pm/PmMarketHealth";
import TaaWorkspace from "../pages/pm/TaaWorkspace";
import PmHoldings from "../pages/pm/PmHoldings";
import PmPack from "../pages/pm/PmPack";
import PsInbox from "../pages/ps/PsInbox";
import MarketResearch from "../pages/ps/MarketResearch";
import FinaliseProducts from "../pages/ps/FinaliseProducts";
import HouseViewRecords from "../pages/ps/HouseViewRecords";
import ProductShelfPage from "../pages/ps/ProductShelfPage";
import AssetClassViews from "../pages/ps/AssetClassViews";
import AssetClassViewPage from "../pages/ps/AssetClassViewPage";
import ClientLayout from "../pages/client/ClientLayout";
import ClientOverview from "../pages/client/ClientOverview";
import ClientDocuments from "../pages/client/ClientDocuments";
import ClientUploadNotes from "../pages/client/ClientUploadNotes";

/** Shared Client 360 (all roles, permissions differ per role inside pages). */
const client360 = {
  path: "clients/:clientId",
  element: <ClientLayout />,
  children: [
    { index: true, element: <ClientOverview /> },
    { path: "documents", element: <ClientDocuments /> },
    { path: "upload-notes", element: <ClientUploadNotes /> },
    { path: "review-pack", element: <PackReview embedded /> },
    ...["dashboard", "ips", "3l", "allocation", "notes", "history"].map((path) => ({
      path,
      element: <Navigate to="../documents" relative="path" replace />,
    })),
  ],
};

export const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/rm/clients" replace /> },
  { path: "/ic/*", element: <LegacyIcRedirect /> },
  { path: "/legacy-chat", element: <ChatContainer /> },
  {
    path: "/rm",
    element: <AppShell />,
    children: [
      { path: "house-views", element: <HouseViewRecords /> },
      { index: true, element: <Navigate to="clients" replace /> },
      { path: "clients", element: <ClientBook /> },
      { path: "assistant", element: <RmAssistant /> },
      client360,
      { path: "clients/:clientId/onboarding/notes", element: <OnboardingNotes /> },
      { path: "clients/:clientId/onboarding/summary", element: <OnboardingSummary /> },
      { path: "clients/:clientId/ips-draft", element: <IpsDraft /> },
      { path: "clients/:clientId/ips-approval", element: <IpsApproval /> },
      { path: "clients/:clientId/review/start", element: <QuarterlyReviewStart /> },
      { path: "clients/:clientId/review/pack", element: <PackReview /> },
    ],
  },
  {
    path: "/pm",
    element: <AppShell />,
    children: [
      { path: "house-views", element: <HouseViewRecords /> },
      { index: true, element: <Navigate to="inbox" replace /> },
      { path: "inbox", element: <PmInbox /> },
      { path: "clients", element: <ClientBook /> },
      { path: "assistant", element: <PmAssistant /> },
      client360,
      { path: "requests/:clientId/3l", element: <ThreeLBuilder /> },
      { path: "requests/:clientId/saa", element: <SaaBuilder /> },
      // Before the 3L split there was one Edit weights page; send old links to the bucket picker.
      { path: "requests/:clientId/saa/weights", element: <Navigate to=".." relative="path" replace /> },
      { path: "requests/:clientId/saa/review", element: <SaaReview /> },
      { path: "requests/:clientId/saa/:bucket", element: <SaaBuilder /> },
      { path: "requests/:clientId/saa/:bucket/weights", element: <SaaWeights /> },
      { path: "cases/:clientId/products", element: <ProductRecommendations /> },
      { path: "cases/:clientId/insights", element: <Navigate to="../products" relative="path" replace /> },
      { path: "cases/:clientId/market-health", element: <PmMarketHealth /> },
      { path: "cases/:clientId/taa", element: <TaaWorkspace /> },
      { path: "cases/:clientId/holdings", element: <PmHoldings /> },
      { path: "cases/:clientId/pack", element: <PmPack /> },
    ],
  },
  {
    path: "/ps",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="inbox" replace /> },
      { path: "inbox", element: <PsInbox /> },
      { path: "clients", element: <ClientBook /> },
      { path: "assistant", element: <MarketResearch /> },
      { path: "house-views", element: <HouseViewRecords /> },
      { path: "shelf", element: <ProductShelfPage /> },
      { path: "asset-views", element: <AssetClassViews /> },
      { path: "asset-views/:assetClass", element: <AssetClassViewPage /> },
      client360,
      { path: "cases/:clientId/market", element: <Navigate to="/ps/assistant" replace /> },
      { path: "cases/:clientId/finalise", element: <FinaliseProducts /> },
    ],
  },
]);
