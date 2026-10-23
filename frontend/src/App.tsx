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
        <span className="brand">Order Plan</span>
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
