import type { Metadata } from "next";
import { AdminProvider } from "@/features/admin/admin-store";

export const metadata: Metadata = { title: "Admin · ChronoTrip" };

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return <AdminProvider>{children}</AdminProvider>;
}
