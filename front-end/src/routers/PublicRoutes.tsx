import AppLayout from "@Shore/layouts/AppLayout";
import PageChat from "@Shore/pages/Chat";
import PageMain from "@Shore/pages/Main";
import { Routes, Route } from "react-router-dom";

export default function PublicRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<PageMain />} />
        <Route path="/chat" element={<PageChat />} />
      </Route>
    </Routes>
  );
}
