import { createBrowserRouter, Navigate } from "react-router-dom";
import AppShell from "../layouts/AppShell";
import { ChatContainer } from "../components/Chat/ChatContainer";
import ClientBook from "../pages/rm/ClientBook";
import RmAssistant from "../pages/rm/RmAssistant";
import OnboardingNotes from "../pages/rm/OnboardingNotes";
import OnboardingSummary from "../pages/rm/OnboardingSummary";
import IpsDraft from "../pages/rm/IpsDraft";
import IpsApproval from "../pages/rm/IpsApproval";
import QuarterlyReviewStart from "../pages/rm/QuarterlyReviewStart";
import PackReview from "../pages/rm/PackReview";
import IcInbox from "../pages/ic/IcInbox";
import ThreeLBuilder from "../pages/ic/ThreeLBuilder";
import SaaBuilder from "../pages/ic/SaaBuilder";
import PortfolioInsights from "../pages/ic/PortfolioInsights";
import TaaWorkspace from "../pages/ic/TaaWorkspace";
import IcPack from "../pages/ic/IcPack";
import PsInbox from "../pages/ps/PsInbox";
import MarketResearch from "../pages/ps/MarketResearch";
import FinaliseProducts from "../pages/ps/FinaliseProducts";
import HouseViewRecords from "../pages/shared/HouseViewRecords";
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
  { path: "/legacy-chat", element: <ChatContainer /> },
  {
    path: "/rm",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="clients" replace /> },
      { path: "clients", element: <ClientBook /> },
      { path: "assistant", element: <RmAssistant /> },
      { path: "house-view", element: <HouseViewRecords /> },
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
    path: "/ic",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="inbox" replace /> },
      { path: "inbox", element: <IcInbox /> },
      { path: "house-view", element: <HouseViewRecords /> },
      client360,
      { path: "requests/:clientId/3l", element: <ThreeLBuilder /> },
      { path: "requests/:clientId/saa", element: <SaaBuilder /> },
      { path: "cases/:clientId/insights", element: <PortfolioInsights /> },
      { path: "cases/:clientId/taa", element: <TaaWorkspace /> },
      { path: "cases/:clientId/pack", element: <IcPack /> },
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
      { path: "house-view", element: <HouseViewRecords /> },
      client360,
      { path: "cases/:clientId/market", element: <Navigate to="/ps/assistant" replace /> },
      { path: "cases/:clientId/finalise", element: <FinaliseProducts /> },
    ],
  },
]);
