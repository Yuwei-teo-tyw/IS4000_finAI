import { createBrowserRouter, Navigate, useParams } from "react-router-dom";
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
import PmReview from "../pages/pm/PmReview";
import PmInbox from "../pages/pm/PmInbox";
import PmIpsReview from "../pages/pm/PmIpsReview";
import HouseViewRecords from "../pages/pm/HouseViewRecords";
import ProductShelfPage from "../pages/pm/ProductShelfPage";
import AssetClassViews from "../pages/pm/AssetClassViews";
import AssetClassViewPage from "../pages/pm/AssetClassViewPage";
import ClientLayout from "../pages/client/ClientLayout";
import ClientDocuments from "../pages/client/ClientDocuments";
import ClientUploadNotes from "../pages/client/ClientUploadNotes";
import ClientPortfolio from "../pages/client/ClientPortfolio";

/** Shared Client 360 (all roles, permissions differ per role inside pages). */
const client360 = {
  path: "clients/:clientId",
  element: <ClientLayout />,
  children: [
    { index: true, element: <ClientPortfolio /> },
    { path: "documents", element: <ClientDocuments /> },
    { path: "upload-notes", element: <ClientUploadNotes /> },
    { path: "portfolio", element: <Navigate to=".." relative="path" replace /> },
    { path: "review-pack", element: <PackReview embedded /> },
    ...["dashboard", "ips", "3l", "allocation", "notes", "history"].map((path) => ({
      path,
      element: <Navigate to="../documents" relative="path" replace />,
    })),
  ],
};

/** Old PM 3L / SAA deep links (/3l, /saa, /saa/:bucket, /saa/review) land on the single IPS review page. */
function OldPmCase() { const { clientId = "" } = useParams(); return <Navigate to={`/pm/cases/${clientId}/review`} replace />; }
function OldPmRequest() { const { clientId = "" } = useParams(); return <Navigate to={`/pm/requests/${clientId}/ips`} replace />; }

export const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/rm/clients" replace /> },
  { path: "/ic/*", element: <LegacyIcRedirect /> },
  { path: "/ps/*", element: <Navigate to="/pm/inbox" replace /> }, // the Product Specialist role was removed; old URLs land on the PM inbox
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
      { path: "requests/:clientId/ips", element: <PmIpsReview /> },
      // Old 3L / SAA deep links land on the single IPS review page.
      { path: "requests/:clientId/3l", element: <OldPmRequest /> },
      { path: "requests/:clientId/saa/*", element: <OldPmRequest /> },
      { path: "shelf", element: <ProductShelfPage /> },
      { path: "asset-views", element: <AssetClassViews /> },
      { path: "asset-views/:assetClass", element: <AssetClassViewPage /> },
      { path: "cases/:clientId/review", element: <PmReview /> },
      { path: "cases/:clientId/*", element: <OldPmCase /> }, // old research/products/taa/holdings/pack deep links
    ],
  },
]);
