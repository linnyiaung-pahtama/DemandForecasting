import { BrowserRouter, NavLink, Route, Routes, useParams } from 'react-router-dom'
import UploadPage from './pages/UploadPage'

function Placeholder({ title }: { title: string }) {
  const { id } = useParams()
  return (
    <div className="card">
      <h2>{title}</h2>
      <p className="muted">{id ? `Run ${id}: ` : ''}This page is not built yet.</p>
    </div>
  )
}

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
          <Route path="/runs/:id" element={<Placeholder title="Order plan" />} />
          <Route path="/runs/:id/suppliers" element={<Placeholder title="Supplier summary" />} />
          <Route path="/settings" element={<Placeholder title="Supplier settings" />} />
          <Route path="/history" element={<Placeholder title="Run history" />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
