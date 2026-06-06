import AppLayout from "@Shore/layouts/AppLayout";
import AuthGuard from "@Shore/components/AuthGuard";
import PageChat from "@Shore/pages/Chat";
import PageDashboard from "@Shore/pages/Dashboard";
import PageMemory from "@Shore/pages/Memory";
import PageChronicles from "@Shore/pages/Chronicles";
import PageLogin from "@Shore/pages/Login";
import PageForbidden from "@Shore/pages/Forbidden";
import { Routes, Route } from "react-router-dom";

export default function PublicRoutes() {
  return (
    <Routes>
      {/* Public — no auth required */}
      <Route path="/login" element={<PageLogin />} />
      <Route path="/403" element={<PageForbidden />} />
      <Route element={<AppLayout />}>
        {/* Public-within-shell — Chronicles is a public changelog */}
        <Route path="/chronicles" element={<PageChronicles />} />
        <Route path="/chronicles/:slug" element={<PageChronicles />} />

        {/* Any authenticated user */}
        <Route path="/" element={
          <AuthGuard><PageDashboard /></AuthGuard>
        } />
        <Route path="/chat" element={
          <AuthGuard><PageChat /></AuthGuard>
        } />

        {/* Admin only */}
        <Route path="/memory" element={
          <AuthGuard role="admin"><PageMemory /></AuthGuard>
        } />
      </Route>
    </Routes>
  );
}
