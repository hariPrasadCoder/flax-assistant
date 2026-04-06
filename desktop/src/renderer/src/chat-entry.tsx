import ReactDOM from 'react-dom/client'
import './styles/global.css'
import ChatApp from './ChatApp'

// No StrictMode — double-mount behavior causes duplicate greeting/fetch side effects
ReactDOM.createRoot(document.getElementById('root')!).render(<ChatApp />)
