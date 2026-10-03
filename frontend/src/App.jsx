import { Route, Routes } from 'react-router-dom'
import EditorPage from './pages/EditorPage'
import EmbedPage from './pages/EmbedPage'
import HomePage from './pages/HomePage'
import MapPage from './pages/MapPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/maps/:mapId" element={<MapPage />} />
      <Route path="/editor" element={<EditorPage />} />
      <Route path="/editor/:mapId" element={<EditorPage />} />
      <Route path="/embed" element={<EmbedPage />} />
      <Route path="/embed/:mapId" element={<EmbedPage />} />
    </Routes>
  )
}
