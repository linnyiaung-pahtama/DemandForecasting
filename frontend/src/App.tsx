import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import HistoryPage from './pages/HistoryPage'
import PlanPage from './pages/PlanPage'
import SettingsPage from './pages/SettingsPage'
import SupplierPage from './pages/SupplierPage'
import UploadPage from './pages/UploadPage'

export default function App() {
  return (
    <BrowserRouter>
      <nav className="topnav">
        <span className="brand">
          {/* a taped carton */}
          <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
            <rect x="2" y="5" width="18" height="14" rx="2" fill="#c8901a" />
            <path d="M2 9h18" stroke="#172a31" strokeWidth="1.2" />
            <rect x="9" y="5" width="4" height="6" fill="#f6e3b6" />
          </svg>
          Order Plan
        </span>
        <NavLink to="/" end>
          New plan
        </NavLink>
        <NavLink to="/history">History</NavLink>
        <NavLink to="/settings">Supplier settings</NavLink>
      </nav>
      <main className="page">
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/runs/:id" element={<PlanPage />} />
          <Route path="/runs/:id/suppliers" element={<SupplierPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
