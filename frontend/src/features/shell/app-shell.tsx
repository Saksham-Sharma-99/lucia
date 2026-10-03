import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useMatches, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  BotIcon,
  Building2Icon,
  LibraryIcon,
  ListChecksIcon,
  LogOutIcon,
  MessagesSquareIcon,
  MoonIcon,
  SunIcon,
  WorkflowIcon,
} from "lucide-react";

import { logoutMutation } from "@/api/generated/@tanstack/react-query.gen";
import type { UserOut } from "@/api/generated/types.gen";
import { Avatar } from "@/components/shared/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { NotificationBell } from "@/features/notifications/bell";
import { toastError } from "@/lib/problem";
import { useTheme } from "@/lib/theme";

const NAV = [
  { to: "/playground", label: "Playground", icon: MessagesSquareIcon },
  { to: "/runs", label: "Agent runs", icon: ListChecksIcon },
  { to: "/agents", label: "Agents", icon: BotIcon },
  { to: "/firm-mappings", label: "Firm mappings", icon: WorkflowIcon },
  { to: "/firms", label: "Firms", icon: Building2Icon },
  { to: "/registry", label: "Registry", icon: LibraryIcon },
] as const;

export function AppShell({ user }: { user: UserOut }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const fullBleed = useMatches({ select: (ms) => ms.some((m) => m.staticData.fullBleed) });
  return (
    // Collapses to an icon rail (the button, the rail edge or ⌘B); the sidebar keeps the choice
    // in a cookie, read back here.
    <SidebarProvider defaultOpen={!document.cookie.includes("sidebar_state=false")}>
      <Sidebar collapsible="icon">
        <SidebarHeader className="flex-row items-center justify-between px-4 pt-5 pb-4 group-data-[collapsible=icon]:px-2">
          <Link
            to="/agents"
            className="text-brass text-lg font-semibold tracking-tight group-data-[collapsible=icon]:hidden"
          >
            lucia
          </Link>
          <SidebarTrigger className="hidden md:inline-flex" />
        </SidebarHeader>
        <SidebarContent className="px-2">
          <SidebarMenu>
            {NAV.map(({ to, label, icon: Icon }) => (
              <SidebarMenuItem key={to}>
                <SidebarMenuButton
                  isActive={pathname.startsWith(to)}
                  tooltip={label}
                  render={<Link to={to} />}
                >
                  <Icon />
                  <span>{label}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarContent>
        <SidebarFooter className="p-2">
          <SidebarMenu>
            <SidebarMenuItem>
              <NotificationBell />
            </SidebarMenuItem>
          </SidebarMenu>
          <UserMenu user={user} />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
      <SidebarInset>
        <div className="flex h-12 items-center px-4 md:hidden">
          <SidebarTrigger />
        </div>
        <main
          className={
            fullBleed ? "h-svh w-full" : "mx-auto w-full max-w-[1180px] px-6 py-8 md:px-10"
          }
        >
          <Outlet />
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}

function UserMenu({ user }: { user: UserOut }) {
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logout = useMutation({
    ...logoutMutation(),
    onSuccess: () => {
      queryClient.clear();
      void navigate({ to: "/login" });
    },
    onError: (e) => toastError(e, "Sign out failed"),
  });
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            aria-label={`Account: ${user.display_name}`}
            className="hover:bg-sidebar-accent flex w-full items-center gap-2.5 rounded-md p-2 text-left text-sm group-data-[collapsible=icon]:p-0"
          />
        }
      >
        <Avatar label={user.display_name} colorKey={user.username} size="sm" />
        <span className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
          <span className="block truncate font-medium">{user.display_name}</span>
          <span className="text-muted-foreground block truncate text-xs">@{user.username}</span>
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-52">
        <DropdownMenuItem onClick={toggle}>
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          {theme === "dark" ? "Light theme" : "Dark theme"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => logout.mutate({})}>
          <LogOutIcon />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
