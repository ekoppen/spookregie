import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { logout } from "../api/auth";

const links = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/mirror-scare", label: "Scare-video's", end: false },
  { to: "/scare", label: "Scare", end: false },
  { to: "/ha", label: "Home Assistant", end: false },
  { to: "/logs", label: "Logs", end: false },
  { to: "/outputs", label: "Outputs", end: false },
  { to: "/sources", label: "Sources", end: false },
  { to: "/settings", label: "Instellingen", end: false },
];

export default function Layout() {
  const navigate = useNavigate();

  async function handleLogout() {
    try {
      await logout();
    } finally {
      // Gebruiker wil sowieso weg uit het beheerde gebied, ook als de
      // logout-call zelf mislukte (bv. sessie al verlopen).
      navigate("/login");
    }
  }

  return (
    <div>
      <nav className="breaker-row">
        <div className="breaker-row__switches">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) => "breaker" + (isActive ? " breaker--active" : "")}
            >
              <span className="breaker__led" />
              {link.label}
            </NavLink>
          ))}
        </div>
        <button type="button" className="breaker-row__kill" onClick={handleLogout}>
          <span className="breaker__led" />
          Uitloggen
        </button>
      </nav>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
