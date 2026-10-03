import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import '@xyflow/react/dist/style.css'
import '@shizuha/atlas/styles.css'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter basename="/atlas">
      <App />
    </BrowserRouter>
  </StrictMode>,
)
